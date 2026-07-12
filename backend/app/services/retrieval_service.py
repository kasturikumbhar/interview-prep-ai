"""
Retrieval Service — production pipeline with:
1. Embedding cache (in-memory LRU)
2. Query rewriting with conversational context (fixes "explain that more")
3. Intent classification → metadata pre-filtering
4. Hybrid BM25 + dense search
5. RRF score fusion
6. Cross-encoder reranking (bge-reranker-base on MPS)
7. Citation generation (Source: file → heading path)
8. Confidence fallback (low confidence → LLM general knowledge + disclosure)
"""
import re
import math
import asyncio
import hashlib
from typing import Optional
from collections import defaultdict
from app.services.llm_service import LLMService
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()
llm = LLMService()

# ── Embedding cache (LRU-style, max 1000 entries) ─────────────────────────────
_embed_cache: dict[str, list[float]] = {}
_embed_order: list[str] = []
MAX_EMBED_CACHE = 1000


async def _embed_cached(text: str) -> list[float]:
    key = hashlib.md5(text.encode()).hexdigest()
    if key in _embed_cache:
        return _embed_cache[key]

    embedding = await llm.embed(text)

    # LRU eviction
    if len(_embed_cache) >= MAX_EMBED_CACHE:
        oldest = _embed_order.pop(0)
        _embed_cache.pop(oldest, None)

    _embed_cache[key] = embedding
    _embed_order.append(key)
    return embedding


def cache_stats() -> dict:
    return {"embed_cache_size": len(_embed_cache), "max": MAX_EMBED_CACHE}


# ── Conversational Query Rewriting ────────────────────────────────────────────
REWRITE_PROMPT = """You are a search query optimizer for a technical interview prep system.

Conversation history (last few turns for context):
{history}

Current query: {query}

Rules:
1. If the query refers to "that", "it", "this", "the above", "explain more" — resolve the reference using conversation history
2. Expand vague technical queries with relevant terms and synonyms
3. Keep it concise (under 30 words)
4. Return ONLY the expanded query, no explanation

Examples:
History: [User asked about Kafka consumer groups]
Query: "explain that more"
Output: "Apache Kafka consumer group rebalancing partition assignment coordinator protocol"

History: []
Query: "two pointers"
Output: "two pointer algorithm array technique left right pointer shrink expand O(n) time complexity"

History: [User asked about Spring transactions]
Query: "what about rollback?"
Output: "Spring @Transactional rollback exception propagation commit savepoint"

Output:"""


async def rewrite_query(query: str, conversation_history: list[dict] = None) -> str:
    """Expand query with conversation context to resolve references."""
    # Build compact history string (last 4 messages)
    history_str = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_str = "\n".join(f"{m['role'].upper()}: {m['content'][:150]}" for m in recent)

    # Short specific queries don't need rewriting unless they're references
    reference_words = {"that", "it", "this", "above", "more", "explain more", "elaborate", "continue"}
    is_reference = any(w in query.lower() for w in reference_words)
    is_short = len(query.split()) < 4

    if not is_reference and not is_short:
        return query

    try:
        prompt = REWRITE_PROMPT.format(
            history=history_str or "No previous conversation",
            query=query,
        )
        response = await llm.chat([{"role": "user", "content": prompt}], mode="chat")
        rewritten = response.strip().split("\n")[0].strip()
        if rewritten and len(rewritten) > len(query):
            logger.info(f"Query rewrite: '{query}' → '{rewritten[:80]}'")
            return rewritten
    except Exception as e:
        logger.warning(f"Query rewrite failed: {e}")
    return query


# ── Intent Classification ─────────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "dsa": ["leetcode", "algorithm", "array", "tree", "graph", "dp", "dynamic programming",
            "binary search", "heap", "trie", "backtracking", "two pointers", "sliding window",
            "complexity", "big o", "sort", "linked list", "stack", "queue", "hash", "recursion"],
    "system_design": ["design", "scale", "distributed", "kafka", "redis", "cdn", "load balancer",
                      "database", "cache", "api", "microservice", "event", "stream", "architecture",
                      "rate limit", "sharding", "replication", "consistency", "cap theorem"],
    "java": ["spring", "jvm", "gc", "thread", "concurrent", "synchronized", "bean", "annotation",
             "hibernate", "maven", "gradle", "collection", "stream", "lambda", "interface",
             "transactional", "autowired", "reactor", "webflux", "springboot"],
    "python": ["pyspark", "spark", "pandas", "async", "asyncio", "generator", "decorator",
               "glue", "airflow", "delta", "lake", "etl", "pipeline", "dataframe", "rdd",
               "broadcast", "partition", "watermark"],
    "aws": ["s3", "lambda", "ec2", "ecs", "eks", "sqs", "sns", "glue", "step functions",
            "dynamodb", "aurora", "kinesis", "cloudwatch", "iam", "vpc", "rds", "fargate",
            "cloudfront", "elasticache", "emr"],
    "behavioral": ["star", "situation", "conflict", "leadership", "incident", "production",
                   "team", "stakeholder", "decision", "challenge", "feedback", "mentor",
                   "disagreement", "ownership", "deadline"],
}


def classify_intent(query: str) -> Optional[str]:
    query_lower = query.lower()
    scores: dict[str, int] = defaultdict(int)
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                scores[topic] += 1
    if not scores:
        return None
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] >= 2 else None


# ── BM25 ──────────────────────────────────────────────────────────────────────
class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict] = []
        self._index: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._doc_lengths: list[int] = []
        self._avg_length: float = 0.0

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]+", text.lower())

    def index(self, docs: list[dict]):
        self._docs = docs
        self._index = defaultdict(list)
        self._doc_lengths = []
        for i, doc in enumerate(docs):
            tokens = self._tokenize(doc.get("content", ""))
            self._doc_lengths.append(len(tokens))
            freq: dict[str, int] = defaultdict(int)
            for t in tokens:
                freq[t] += 1
            for term, count in freq.items():
                self._index[term].append((i, count))
        self._avg_length = sum(self._doc_lengths) / max(len(self._doc_lengths), 1)

    def search(self, query: str, k: int = 20) -> list[tuple[float, dict]]:
        if not self._docs:
            return []
        tokens = self._tokenize(query)
        N = len(self._docs)
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokens):
            postings = self._index.get(term, [])
            if not postings:
                continue
            df = len(postings)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            for doc_idx, tf in postings:
                dl = self._doc_lengths[doc_idx]
                norm_tf = tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self._avg_length)
                )
                scores[doc_idx] += idf * norm_tf
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        return [(score, self._docs[idx]) for idx, score in ranked]


# ── RRF Fusion ────────────────────────────────────────────────────────────────
def reciprocal_rank_fusion(
    dense_results: list[dict],
    bm25_results: list[tuple[float, dict]],
    k: int = 60,
    top_n: int = 20,
) -> list[dict]:
    rrf_scores: dict[str, float] = defaultdict(float)
    docs_by_id: dict[str, dict] = {}

    for rank, doc in enumerate(dense_results):
        meta = doc.get("metadata", {})
        doc_id = meta.get("chunk_id") or meta.get("heading_path") or doc["content"][:50]
        rrf_scores[doc_id] += 1.0 / (k + rank + 1)
        docs_by_id[doc_id] = doc

    for rank, (_, doc) in enumerate(bm25_results):
        meta = doc.get("metadata", {})
        doc_id = doc.get("id") or meta.get("chunk_id") or doc.get("content", "")[:50]
        rrf_scores[doc_id] += 1.0 / (k + rank + 1)
        if doc_id not in docs_by_id:
            docs_by_id[doc_id] = {
                "content":  doc.get("content", ""),
                "metadata": meta,
                "score":    0.0,
            }

    ranked = sorted(rrf_scores.items(), key=lambda x: -x[1])[:top_n]
    return [docs_by_id[doc_id] for doc_id, _ in ranked if doc_id in docs_by_id]


# ── Reranker ──────────────────────────────────────────────────────────────────
_reranker_model = None
_reranker_status: Optional[bool] = None  # None=not tried, True=ok, False=unavailable


def _load_reranker() -> bool:
    global _reranker_model, _reranker_status
    if _reranker_status is not None:
        return _reranker_status
    try:
        from sentence_transformers import CrossEncoder
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _reranker_model = CrossEncoder("BAAI/bge-reranker-base", device=device)
        _reranker_status = True
        logger.info(f"Reranker loaded: BAAI/bge-reranker-base on {device}")
    except ImportError:
        logger.warning("sentence-transformers not installed. pip install sentence-transformers torch")
        _reranker_status = False
    except Exception as e:
        logger.warning(f"Reranker unavailable: {e}")
        _reranker_status = False
    return _reranker_status


def rerank(query: str, docs: list[dict], top_k: int = 5) -> tuple[list[dict], list[float]]:
    """Returns (reranked_docs, scores)."""
    if not docs:
        return [], []
    if not _load_reranker() or len(docs) <= top_k:
        return docs[:top_k], [1.0] * min(len(docs), top_k)
    try:
        pairs = [(query, doc["content"][:512]) for doc in docs]
        raw_scores = _reranker_model.predict(pairs)
        scored = sorted(zip(raw_scores, docs), key=lambda x: -x[0])
        top = scored[:top_k]
        return [d for _, d in top], [float(s) for s, _ in top]
    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
        return docs[:top_k], [1.0] * top_k


# ── BM25 index (lazy, rebuilt on demand) ─────────────────────────────────────
_bm25_index: Optional[BM25] = None
_bm25_topic: Optional[str] = None


async def _get_bm25_index(topic: Optional[str] = None) -> BM25:
    global _bm25_index, _bm25_topic
    if _bm25_index is not None and _bm25_topic == topic:
        return _bm25_index

    from app.services.memory_service import MemoryService
    memory = MemoryService()
    topics = [topic] if topic else ["dsa","system_design","java","python","aws","behavioral","general"]
    docs = []
    for t in topics:
        try:
            col = memory._get_or_create_collection(t)
            count = col.count()
            if count == 0:
                continue
            result = col.get(limit=min(count, 3000), include=["documents","metadatas","ids"])
            for doc_id, content, meta in zip(result["ids"], result["documents"], result["metadatas"]):
                docs.append({"id": doc_id, "content": content, "metadata": meta or {}})
        except Exception as e:
            logger.warning(f"BM25 index fetch failed for {t}: {e}")

    bm25 = BM25()
    bm25.index(docs)
    _bm25_index = bm25
    _bm25_topic = topic
    logger.info(f"BM25 index built: {len(docs)} docs, topic={topic}")
    return bm25


def invalidate_bm25_cache():
    global _bm25_index
    _bm25_index = None
    logger.info("BM25 cache invalidated")


# ── Confidence scoring ────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.35  # below this → low confidence fallback

def _compute_confidence(reranked_scores: list[float], chunks: list[dict]) -> float:
    """Confidence = average of top-3 reranker scores, or cosine scores if no reranker."""
    if reranked_scores and reranked_scores[0] != 1.0:
        # Real reranker scores (range roughly -10 to +10, normalize)
        top3 = reranked_scores[:3]
        # Sigmoid normalization
        import math
        normalized = [1 / (1 + math.exp(-s)) for s in top3]
        return sum(normalized) / len(normalized)
    # Fall back to cosine scores
    scores = [c.get("score", 0) for c in chunks[:3]]
    return sum(scores) / max(len(scores), 1)


# ── Citation builder ──────────────────────────────────────────────────────────
def build_citations(chunks: list[dict]) -> str:
    """
    Build citation list for LLM to include in answer.
    Format: [1] filename → heading path
    """
    seen = set()
    citations = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        source = meta.get("source_path", "").split("/")[-1] or "notes"
        heading_path = meta.get("heading_path", meta.get("heading", ""))
        key = f"{source}:{heading_path}"
        if key not in seen:
            seen.add(key)
            citations.append(f"[{i}] {source} → {heading_path}" if heading_path else f"[{i}] {source}")
    return "\n".join(citations)


# ── Main retrieval pipeline ───────────────────────────────────────────────────
async def retrieve(
    query: str,
    topic: Optional[str] = None,
    k_final: int = 5,
    conversation_history: list[dict] = None,
    use_reranker: bool = True,
    use_query_rewrite: bool = True,
) -> tuple[list[dict], str, float]:
    """
    Returns: (chunks, rewritten_query, confidence_score)
    """
    from app.services.memory_service import MemoryService
    memory = MemoryService()

    # Step 1: Query rewriting with conversation context
    rewritten = (
        await rewrite_query(query, conversation_history)
        if use_query_rewrite else query
    )

    # Step 2: Intent classification
    detected_topic = topic or classify_intent(rewritten)

    # Step 3: Parallel dense + BM25
    dense_task = memory.search(rewritten, topic=detected_topic, k=20)
    bm25_task  = _get_bm25_index(detected_topic)
    dense_results, bm25_index = await asyncio.gather(dense_task, bm25_task)
    bm25_results = bm25_index.search(rewritten, k=20)

    # Step 4: RRF fusion
    fused = reciprocal_rank_fusion(dense_results, bm25_results, top_n=20)
    if not fused:
        return [], rewritten, 0.0

    # Step 5: Reranking
    if use_reranker:
        final, scores = rerank(rewritten, fused, top_k=k_final)
    else:
        final, scores = fused[:k_final], [c.get("score", 0) for c in fused[:k_final]]

    confidence = _compute_confidence(scores, final)

    logger.info(
        f"Retrieval: dense={len(dense_results)} bm25={len(bm25_results)} "
        f"fused={len(fused)} final={len(final)} "
        f"confidence={confidence:.2f} topic={detected_topic}"
    )
    return final, rewritten, confidence


async def build_context(
    query: str,
    topic: Optional[str] = None,
    conversation_history: list[dict] = None,
) -> tuple[str, str, float, list[dict]]:
    """
    Returns: (context_string, rewritten_query, confidence, chunks)
    """
    chunks, rewritten, confidence = await retrieve(
        query,
        topic=topic,
        conversation_history=conversation_history,
    )

    if not chunks or confidence < CONFIDENCE_THRESHOLD:
        low_conf_note = (
            f"\n\n⚠️ Note: Retrieval confidence is low ({confidence:.0%}). "
            "The following answer is drawn from general knowledge, not your personal notes."
        ) if confidence < CONFIDENCE_THRESHOLD else ""
        return low_conf_note, rewritten, confidence, []

    # Build context with source attribution
    citations = build_citations(chunks)
    lines = [
        "--- Retrieved context (semantic chunks, reranked) ---",
        f"Sources:\n{citations}",
        "",
    ]
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        heading_path = meta.get("heading_path", meta.get("heading", "?"))
        chunk_type   = meta.get("chunk_type", "text")
        source       = meta.get("source_path", "").split("/")[-1]
        difficulty   = meta.get("difficulty", "")
        diff_str     = f" | difficulty={difficulty}" if difficulty and difficulty != "unknown" else ""
        lines.append(f"\n[{i}] {heading_path} | type={chunk_type}{diff_str} | {source}")
        lines.append(chunk["content"])
    lines.append("--- End context ---")
    lines.append(
        "\nWhen answering, cite sources using [1], [2] etc. referencing the sources listed above. "
        "If information is not in the context, say 'This wasn't found in your notes — from general knowledge:'"
    )

    return "\n".join(lines), rewritten, confidence, chunks