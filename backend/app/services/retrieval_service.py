"""
Retrieval Service — production RAG pipeline.

Pipeline:
  Query
    → Query Rewriting (expand vague terms)
    → Intent Classification (which collection/topic)
    → Parallel: BM25 keyword search + Dense vector search
    → Score fusion (RRF - Reciprocal Rank Fusion)
    → Top-20
    → Cross-encoder reranking
    → Top-5

Embedding model recommendation:
  mxbai-embed-large (via Ollama) > nomic-embed-text for semantic tasks.
  - Better on MTEB benchmark for retrieval tasks
  - Stronger at capturing semantic similarity vs keyword proximity
  - Runs well on Apple Silicon via Ollama
  - Pull with: ollama pull mxbai-embed-large

  To switch: just change EMBED_MODEL in .env.
  The embedding interface is abstracted so swapping is one config change.

Reranker:
  bge-reranker-base via sentence-transformers.
  Runs on MPS (Apple Silicon GPU) automatically.
  Install: pip install sentence-transformers
  First run downloads ~270MB model.
"""
import re
import json
import math
import asyncio
from typing import Optional
from collections import defaultdict
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()
llm = LLMService()
memory = MemoryService()

# ── Embedding cache ───────────────────────────────────────────────────────────
_embed_cache: dict[str, list[float]] = {}
MAX_CACHE_SIZE = 500


async def _embed_cached(text: str) -> list[float]:
    key = text[:200]
    if key in _embed_cache:
        return _embed_cache[key]
    embedding = await llm.embed(text)
    if len(_embed_cache) >= MAX_CACHE_SIZE:
        # Evict oldest 20%
        keys = list(_embed_cache.keys())
        for k in keys[:MAX_CACHE_SIZE // 5]:
            del _embed_cache[k]
    _embed_cache[key] = embedding
    return embedding


# ── Query Rewriting ───────────────────────────────────────────────────────────
REWRITE_PROMPT = """You are a search query optimizer for a technical interview preparation system.

Expand this query into a better search query that will retrieve relevant technical content.
Keep it concise. Add relevant technical terms and synonyms.

Examples:
Input: "explain kafka"
Output: "Apache Kafka architecture message broker producer consumer partitions offsets ISR consumer groups rebalance"

Input: "two pointers"
Output: "two pointers algorithm array technique sliding window left right pointer pattern time complexity O(n)"

Input: "spring transaction"
Output: "Spring @Transactional AOP proxy transaction propagation REQUIRED REQUIRES_NEW rollback commit"

Input query: {query}

Return ONLY the expanded query, no explanation, no quotes."""


async def rewrite_query(query: str) -> str:
    """Expand vague query into richer search terms."""
    if len(query.split()) >= 8:
        # Already specific enough
        return query
    try:
        response = await llm.chat(
            [{"role": "user", "content": REWRITE_PROMPT.format(query=query)}],
            mode="chat",
        )
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
            "complexity", "big o", "sort", "linked list", "stack", "queue", "hash"],
    "system_design": ["design", "scale", "distributed", "kafka", "redis", "cdn", "load balancer",
                      "database", "cache", "api", "microservice", "event", "stream", "architecture"],
    "java": ["spring", "jvm", "gc", "thread", "concurrent", "synchronized", "bean", "annotation",
             "hibernate", "maven", "gradle", "collection", "stream", "lambda", "interface"],
    "python": ["pyspark", "spark", "pandas", "async", "asyncio", "generator", "decorator",
               "glue", "airflow", "delta", "lake", "etl", "pipeline", "dataframe"],
    "aws": ["s3", "lambda", "ec2", "ecs", "eks", "sqs", "sns", "glue", "step functions",
            "dynamodb", "aurora", "kinesis", "cloudwatch", "iam", "vpc", "rds"],
    "behavioral": ["star", "situation", "conflict", "leadership", "incident", "production",
                   "team", "stakeholder", "decision", "challenge", "feedback", "mentor"],
}


def classify_intent(query: str) -> Optional[str]:
    """Classify query to a topic for metadata pre-filtering."""
    query_lower = query.lower()
    scores = defaultdict(int)
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                scores[topic] += 1
    if not scores:
        return None
    best = max(scores, key=lambda t: scores[t])
    # Only filter if we're confident (2+ keyword matches)
    return best if scores[best] >= 2 else None


# ── BM25 Keyword Search ───────────────────────────────────────────────────────
class BM25:
    """
    Simple in-memory BM25 over ChromaDB documents.
    Called after dense retrieval to provide keyword signal.
    k1=1.5, b=0.75 are standard defaults.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict] = []
        self._index: dict[str, list[tuple[int, int]]] = defaultdict(list)  # term → [(doc_idx, freq)]
        self._doc_lengths: list[int] = []
        self._avg_length: float = 0.0

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]+", text.lower())

    def index(self, docs: list[dict]):
        """Index a list of {'id': str, 'content': str, 'metadata': dict}."""
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
        """Return (score, doc) pairs sorted by BM25 score."""
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
                norm_tf = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self._avg_length))
                scores[doc_idx] += idf * norm_tf

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        return [(score, self._docs[idx]) for idx, score in ranked]


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────
def reciprocal_rank_fusion(
    dense_results: list[dict],   # [{content, metadata, score}]
    bm25_results: list[tuple[float, dict]],  # [(score, {id, content, metadata})]
    k: int = 60,
    top_n: int = 20,
) -> list[dict]:
    """
    RRF score = Σ 1/(k + rank_i) across result lists.
    Fuses dense vector scores with BM25 keyword scores.
    k=60 is standard (from original RRF paper).
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    docs_by_id: dict[str, dict] = {}

    # Dense results
    for rank, doc in enumerate(dense_results):
        doc_id = doc.get("metadata", {}).get("chunk_id") or doc.get("content", "")[:50]
        rrf_scores[doc_id] += 1.0 / (k + rank + 1)
        docs_by_id[doc_id] = doc

    # BM25 results
    for rank, (_, doc) in enumerate(bm25_results):
        doc_id = doc.get("id") or doc.get("content", "")[:50]
        rrf_scores[doc_id] += 1.0 / (k + rank + 1)
        if doc_id not in docs_by_id:
            docs_by_id[doc_id] = {
                "content": doc.get("content", ""),
                "metadata": doc.get("metadata", {}),
                "score": 0.0,
            }

    ranked = sorted(rrf_scores.items(), key=lambda x: -x[1])[:top_n]
    return [docs_by_id[doc_id] for doc_id, _ in ranked if doc_id in docs_by_id]


# ── Reranker ──────────────────────────────────────────────────────────────────
_reranker_model = None
_reranker_available = False


def _load_reranker():
    global _reranker_model, _reranker_available
    if _reranker_model is not None:
        return _reranker_available
    try:
        from sentence_transformers import CrossEncoder
        # bge-reranker-base: ~270MB, runs on MPS (Apple Silicon GPU)
        # Better than jina for technical content
        _reranker_model = CrossEncoder(
            "BAAI/bge-reranker-base",
            device="mps",  # Apple Silicon GPU — auto-falls back to CPU
        )
        _reranker_available = True
        logger.info("Reranker loaded: BAAI/bge-reranker-base on MPS")
    except ImportError:
        logger.warning("sentence-transformers not installed. Skipping reranker. Run: pip install sentence-transformers")
        _reranker_available = False
    except Exception as e:
        logger.warning(f"Reranker load failed: {e}. Continuing without reranker.")
        _reranker_available = False
    return _reranker_available


def rerank(query: str, docs: list[dict], top_k: int = 5) -> list[dict]:
    """
    Rerank docs using cross-encoder. Falls back to original order if unavailable.
    Cross-encoder scores (query, doc) pairs — much more accurate than bi-encoder cosine.
    """
    if not docs:
        return docs

    available = _load_reranker()
    if not available or len(docs) <= top_k:
        return docs[:top_k]

    try:
        pairs = [(query, doc["content"][:512]) for doc in docs]
        scores = _reranker_model.predict(pairs)
        scored = sorted(zip(scores, docs), key=lambda x: -x[0])
        reranked = [doc for _, doc in scored[:top_k]]
        logger.info(f"Reranked {len(docs)} → {top_k} docs")
        return reranked
    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
        return docs[:top_k]


# ── BM25 Index (built lazily from ChromaDB) ───────────────────────────────────
_bm25_index: Optional[BM25] = None
_bm25_topic: Optional[str] = None


async def _get_bm25_index(topic: Optional[str] = None) -> BM25:
    """Build BM25 index from ChromaDB contents. Rebuilds when topic changes."""
    global _bm25_index, _bm25_topic
    if _bm25_index is not None and _bm25_topic == topic:
        return _bm25_index

    # Pull all docs from ChromaDB for this topic
    docs = []
    topics_to_fetch = [topic] if topic else [
        "dsa", "system_design", "java", "python", "aws", "behavioral", "general"
    ]
    for t in topics_to_fetch:
        try:
            col = memory._get_or_create_collection(t)
            count = col.count()
            if count == 0:
                continue
            result = col.get(limit=min(count, 2000), include=["documents", "metadatas", "ids"])
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
    """Call after ingestion to force BM25 rebuild."""
    global _bm25_index
    _bm25_index = None


# ── Main retrieval pipeline ───────────────────────────────────────────────────
async def retrieve(
    query: str,
    topic: Optional[str] = None,
    k_final: int = 5,
    use_reranker: bool = True,
    use_query_rewrite: bool = True,
) -> tuple[list[dict], str]:
    """
    Full pipeline: rewrite → classify → hybrid search → rerank → top-k

    Returns:
        (chunks, rewritten_query)
    """
    # Step 1: Query rewriting
    rewritten = await rewrite_query(query) if use_query_rewrite else query

    # Step 2: Intent classification (use provided topic or auto-detect)
    detected_topic = topic or classify_intent(rewritten)

    # Step 3: Parallel dense + BM25 retrieval
    dense_task = memory.search(rewritten, topic=detected_topic, k=20)
    bm25_task  = _get_bm25_index(detected_topic)

    dense_results, bm25_index = await asyncio.gather(dense_task, bm25_task)
    bm25_results = bm25_index.search(rewritten, k=20)

    # Step 4: RRF fusion
    fused = reciprocal_rank_fusion(dense_results, bm25_results, top_n=20)

    if not fused:
        return [], rewritten

    # Step 5: Reranking
    final = rerank(rewritten, fused, top_k=k_final)

    logger.info(
        f"Retrieval: dense={len(dense_results)} bm25={len(bm25_results)} "
        f"fused={len(fused)} final={len(final)} topic={detected_topic}"
    )
    return final, rewritten


async def build_context(query: str, topic: Optional[str] = None) -> tuple[str, str]:
    """
    Build formatted context string from retrieved chunks.
    Returns (context_string, rewritten_query).
    """
    chunks, rewritten = await retrieve(query, topic=topic)
    if not chunks:
        return "", rewritten

    lines = ["--- Retrieved context (semantically chunked, reranked) ---"]
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        heading_path = meta.get("heading_path", meta.get("heading", "?"))
        chunk_type   = meta.get("chunk_type", "text")
        source       = meta.get("source_file", "unknown").split("/")[-1]
        lines.append(f"\n[{i}] {heading_path} | type={chunk_type} | source={source}")
        lines.append(chunk["content"])
    lines.append("--- End context ---")
    return "\n".join(lines), rewritten
