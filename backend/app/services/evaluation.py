"""
RAG Evaluation Harness — answers "did the reranker actually help?"

Metrics implemented:
  Hit Rate    — did the correct chunk appear in top-k? (recall proxy)
  MRR         — mean reciprocal rank of first relevant result
  Context Precision — what fraction of retrieved chunks are relevant?
  Latency     — end-to-end retrieval time per query

Run:
    python -m app.services.evaluation

Produces a JSON report and prints a summary table.
Store results so you can compare before/after embedding model changes.
"""
import asyncio
import json
import time
from pathlib import Path
from app.services.retrieval_service import retrieve
from app.core.config import get_settings
from app.core.logging import get_logger

logger   = get_logger(__name__)
settings = get_settings()

# ── Golden test set ───────────────────────────────────────────────────────────
# These are (query, expected_keyword_in_retrieved_content) pairs.
# Add your own based on your actual notes.
EVAL_QUERIES: list[dict] = [
    # DSA
    {"query": "two pointers technique",        "topic": "dsa",           "expected": ["two pointer", "left", "right"]},
    {"query": "sliding window maximum",         "topic": "dsa",           "expected": ["sliding window", "window"]},
    {"query": "binary search rotated array",    "topic": "dsa",           "expected": ["binary search", "mid"]},
    {"query": "dynamic programming memoization","topic": "dsa",           "expected": ["dp", "memoization", "memo"]},
    {"query": "graph topological sort",         "topic": "dsa",           "expected": ["topological", "indegree"]},
    # System Design
    {"query": "kafka consumer group rebalancing","topic": "system_design", "expected": ["consumer group", "rebalance", "partition"]},
    {"query": "redis cache eviction policies",   "topic": "system_design", "expected": ["lru", "eviction", "cache"]},
    {"query": "rate limiter distributed",        "topic": "system_design", "expected": ["rate limit", "token bucket", "sliding"]},
    # Java
    {"query": "spring transactional propagation","topic": "java",          "expected": ["transactional", "propagation", "aop"]},
    {"query": "java garbage collection g1",      "topic": "java",          "expected": ["gc", "garbage", "g1"]},
    # AWS
    {"query": "sqs lambda dead letter queue",    "topic": "aws",           "expected": ["sqs", "dlq", "dead letter"]},
    {"query": "s3 presigned url",                "topic": "aws",           "expected": ["presigned", "s3"]},
    # Python / Spark
    {"query": "pyspark broadcast join",          "topic": "python",        "expected": ["broadcast", "join", "spark"]},
    {"query": "spark window function",           "topic": "python",        "expected": ["window", "partition", "rank"]},
    # Behavioral
    {"query": "production incident leadership",  "topic": "behavioral",    "expected": ["incident", "production", "action"]},
]


def _is_relevant(content: str, expected_keywords: list[str]) -> bool:
    """A chunk is relevant if it contains at least one expected keyword."""
    content_lower = content.lower()
    return any(kw.lower() in content_lower for kw in expected_keywords)


async def run_evaluation(k: int = 5) -> dict:
    """Run the full eval set and return metrics dict."""
    hits       = 0
    rr_sum     = 0.0   # for MRR
    precision_sum = 0.0
    latencies  = []
    per_query  = []
    total      = len(EVAL_QUERIES)

    for item in EVAL_QUERIES:
        query    = item["query"]
        topic    = item.get("topic")
        expected = item["expected"]

        t0 = time.perf_counter()
        chunks, rewritten, confidence = await retrieve(
            query, topic=topic, k_final=k, use_query_rewrite=True
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        latencies.append(latency_ms)

        # Hit rate — did relevant content appear anywhere in top-k?
        hit = any(_is_relevant(c["content"], expected) for c in chunks)
        hits += int(hit)

        # MRR — rank of first relevant result
        rr = 0.0
        for rank, chunk in enumerate(chunks, 1):
            if _is_relevant(chunk["content"], expected):
                rr = 1.0 / rank
                break
        rr_sum += rr

        # Context precision — fraction of retrieved chunks that are relevant
        relevant_count = sum(1 for c in chunks if _is_relevant(c["content"], expected))
        precision = relevant_count / max(len(chunks), 1)
        precision_sum += precision

        per_query.append({
            "query":      query,
            "topic":      topic,
            "hit":        hit,
            "rr":         round(rr, 3),
            "precision":  round(precision, 3),
            "latency_ms": latency_ms,
            "confidence": round(confidence, 3),
            "rewritten":  rewritten if rewritten != query else None,
            "top_sources": [
                c.get("metadata", {}).get("heading_path", "?")
                for c in chunks[:3]
            ],
        })

    results = {
        "summary": {
            "total_queries":      total,
            "hit_rate":           round(hits / total, 3),
            "mrr":                round(rr_sum / total, 3),
            "context_precision":  round(precision_sum / total, 3),
            "avg_latency_ms":     round(sum(latencies) / total, 1),
            "p95_latency_ms":     round(sorted(latencies)[int(total * 0.95)], 1),
            "k":                  k,
        },
        "per_query": per_query,
    }
    return results


def print_report(results: dict):
    s = results["summary"]
    print("\n" + "="*55)
    print("  PrepAI RAG Evaluation Report")
    print("="*55)
    print(f"  Queries evaluated : {s['total_queries']}")
    print(f"  Hit Rate @{s['k']}      : {s['hit_rate']:.1%}")
    print(f"  MRR               : {s['mrr']:.3f}")
    print(f"  Context Precision : {s['context_precision']:.1%}")
    print(f"  Avg Latency       : {s['avg_latency_ms']} ms")
    print(f"  P95 Latency       : {s['p95_latency_ms']} ms")
    print("="*55)

    # Per-topic breakdown
    by_topic: dict[str, list] = {}
    for q in results["per_query"]:
        by_topic.setdefault(q["topic"], []).append(q)
    print("\n  By topic:")
    for topic, qs in sorted(by_topic.items()):
        topic_hit = sum(1 for q in qs if q["hit"]) / len(qs)
        print(f"    {topic:<20} hit={topic_hit:.0%}  ({len(qs)} queries)")

    # Misses
    misses = [q for q in results["per_query"] if not q["hit"]]
    if misses:
        print(f"\n  ❌ Misses ({len(misses)}):")
        for m in misses:
            print(f"    · {m['query']}")
            print(f"      top sources: {m['top_sources']}")
    print()


async def main():
    print("Running RAG evaluation (this calls Ollama embed for each query)...")
    results = await run_evaluation(k=5)
    print_report(results)

    # Save to disk
    out = Path(settings.DATA_DIR) / "eval_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"Full results saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
