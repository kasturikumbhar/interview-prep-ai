"""
Retrieval pipeline:
  1. Query rewriting + conversational reference resolution
  2. Intent classification → topic routing
  3. Parallel BM25 + dense search
  4. RRF score fusion (top-20)
  5. bge-reranker-base cross-encoder (top-20 → top-5) on Apple Silicon MPS
  6. Confidence scoring
  7. Citation generation (Source: file → heading path)
  8. Fallback: low confidence → disclose + answer from general knowledge
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

logger   = get_logger(__name__)
settings = get_settings()
llm      = LLMService()

CONFIDENCE_THRESHOLD = 0.35

# ── Embedding LRU cache ───────────────────────────────────────────────────────
_embed_cache: dict[str, list[float]] = {}
_embed_order: list[str] = []
MAX_EMBED_CACHE = 1000


async def _embed_cached(text: str) -> list[float]:
    key = hashlib.md5(text.encode()).hexdigest()
    if key in _embed_cache:
        return _embed_cache[key]
    embedding = await llm.embed(text)
    if len(_embed_cache) >= MAX_EMBED_CACHE:
        oldest = _embed_order.pop(0)
        _embed_cache.pop(oldest, None)
    _embed_cache[key] = embedding
    _embed_order.append(key)
    return embedding


# ── Query rewriting with conversational context ───────────────────────────────
REWRITE_PROMPT = """You are a search query optimizer for a technical interview prep system.

Conversation history:
{history}

Current query: {query}

Rules:
1. If the query says "that", "it", "this", "explain more", "elaborate" — resolve the reference from conversation history
2. Expand short vague queries with relevant technical synonyms
3. Return ONLY the expanded query, under 30 words, no explanation

Output:"""


async def rewrite_query(query: str, conversation_history: list[dict] = None) -> str:
    reference_words = {"that","it","this","above","more","elaborate","continue","explain more"}
    is_reference    = any(w in query.lower() for w in reference_words)
    is_short        = len(query.split()) < 4

    if not is_reference and not is_short:
        return query

    history_str = ""
    if conversation_history:
        history_str = "\n".join(
            f"{m['role'].upper()}: {m['content'][:150]}"
            for m in conversation_history[-4:]
        )

    try:
        prompt   = REWRITE_PROMPT.format(
            history=history_str or "No prior conversation",
            query=query,
        )
        response = await llm.chat([{"role":"user","content":prompt}], mode="chat")
        rewritten = response.strip().split("\n")[0].strip()
        if rewritten and len(rewritten) > len(query):
            logger.info(f"Rewrite: '{query}' → '{rewritten[:80]}'")
            return rewritten
    except Exception as e:
        logger.warning(f"Query rewrite failed: {e}")
    return query


# ── Intent classification ─────────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "dsa":           ["leetcode","algorithm","array","tree","graph","dp","dynamic programming",
                      "binary search","heap","trie","backtracking","two pointers","sliding window",
                      "complexity","big o","sort","linked list","stack","queue","hash","recursion"],
    "system_design": ["design","scale","distributed","kafka","redis","cdn","load balancer",
                      "database","cache","api","microservice","event","stream","architecture",
                      "rate limit","sharding","replication","consistency","cap theorem"],
    "java":          ["spring","jvm","gc","thread","concurrent","synchronized","bean","annotation",
                      "hibernate","maven","gradle","collection","stream","lambda","transactional",
                      "autowired","reactor","webflux"],
    "python":        ["pyspark","spark","pandas","async","asyncio","generator","decorator",
                      "glue","airflow","delta","lake","etl","pipeline","dataframe","broadcast"],
    "aws":           ["s3","lambda","ec2","ecs","eks","sqs","sns","glue","step functions",
                      "dynamodb","aurora","kinesis","cloudwatch","iam","vpc","rds","fargate"],
    "behavioral":    ["star","situation","conflict","leadership","incident","production",
                      "team","stakeholder","decision","challenge","feedback","mentor"],
}


def classify_intent(query: str) -> Optional[str]:
    ql     = query.lower()
    scores: dict[str, int] = defaultdict(int)
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in ql:
                scores[topic] += 1
    if not scores:
        return None
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] >= 2 else None


# ── BM25 ──────────────────────────────────────────────────────────────────────
class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b  = b
        self._docs: list[dict]                        = []
        self._index: dict[str, list[tuple[int,int]]]  = defaultdict(list)
        self._doc_lengths: list[int]                  = []
        self._avg_length: float                       = 0.0

    def _tok(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]+", text.lower())

    def index(self, docs: list[dict]):
        self._docs = docs
        self._index = defaultdict(list)
        self._doc_lengths = []
        for i, doc in enumerate(docs):
            tokens = self._tok(doc.get("content",""))
            self._doc_lengths.append(len(tokens))
            freq: dict[str,int] = defaultdict(int)
            for t in tokens:
                freq[t] += 1
            for term, count in freq.items():
                self._index[term].append((i, count))
        self._avg_length = sum(self._doc_lengths) / max(len(self._doc_lengths), 1)

    def search(self, query: str, k: int = 20) -> list[tuple[float,dict]]:
        if not self._docs:
            return []
        N      = len(self._docs)
        scores: dict[int,float] = defaultdict(float)
        for term in set(self._tok(query)):
            postings = self._index.get(term,[])
            if not postings:
                continue
            df  = len(postings)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            for idx, tf in postings:
                dl      = self._doc_lengths[idx]
                norm_tf = tf*(self.k1+1) / (tf + self.k1*(1-self.b+self.b*dl/self._avg_length))
                scores[idx] += idf * norm_tf
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        return [(score, self._docs[idx]) for idx, score in ranked]


# ── RRF fusion ────────────────────────────────────────────────────────────────
def reciprocal_rank_fusion(
    dense:  list[dict],
    bm25:   list[tuple[float,dict]],
    k:      int = 60,
    top_n:  int = 20,
) -> list[dict]:
    rrf:     dict[str,float] = defaultdict(float)
    by_id:   dict[str,dict]  = {}

    for rank, doc in enumerate(dense):
        meta   = doc.get("metadata",{})
        doc_id = meta.get("chunk_id") or meta.get("heading_path") or doc["content"][:50]
        rrf[doc_id] += 1.0 / (k + rank + 1)
        by_id[doc_id] = doc

    for rank, (_, doc) in enumerate(bm25):
        meta   = doc.get("metadata",{})
        doc_id = doc.get("id") or meta.get("chunk_id") or doc.get("content","")[:50]
        rrf[doc_id] += 1.0 / (k + rank + 1)
        if doc_id not in by_id:
            by_id[doc_id] = {"content": doc.get("content",""), "metadata": meta, "score": 0.0}

    return [by_id[d] for d, _ in sorted(rrf.items(), key=lambda x: -x[1])[:top_n] if d in by_id]


# ── Reranker ──────────────────────────────────────────────────────────────────
_reranker       = None
_reranker_ready: Optional[bool] = None


def _load_reranker() -> bool:
    global _reranker, _reranker_ready
    if _reranker_ready is not None:
        return _reranker_ready
    try:
        from sentence_transformers import CrossEncoder
        import torch
        device   = "mps" if torch.backends.mps.is_available() else "cpu"
        _reranker = CrossEncoder("BAAI/bge-reranker-base", device=device)
        _reranker_ready = True
        logger.info(f"Reranker loaded on {device}")
    except ImportError:
        logger.warning("sentence-transformers not installed — skipping reranker")
        _reranker_ready = False
    except Exception as e:
        logger.warning(f"Reranker unavailable: {e}")
        _reranker_ready = False
    return _reranker_ready


def rerank(query: str, docs: list[dict], top_k: int = 5) -> tuple[list[dict], list[float]]:
    if not docs:
        return [], []
    if not _load_reranker() or len(docs) <= top_k:
        return docs[:top_k], [1.0] * min(len(docs), top_k)
    try:
        pairs  = [(query, doc["content"][:512]) for doc in docs]
        raw    = _reranker.predict(pairs)
        scored = sorted(zip(raw, docs), key=lambda x: -x[0])[:top_k]
        return [d for _, d in scored], [float(s) for s, _ in scored]
    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
        return docs[:top_k], [1.0] * top_k


# ── BM25 index (lazy, per-topic) ──────────────────────────────────────────────
_bm25_index: Optional[BM25] = None
_bm25_topic: Optional[str]  = None


async def _get_bm25_index(topic: Optional[str] = None) -> BM25:
    global _bm25_index, _bm25_topic
    if _bm25_index is not None and _bm25_topic == topic:
        return _bm25_index

    from app.services.memory_service import MemoryService
    memory  = MemoryService()
    topics  = [topic] if topic else ["dsa","system_design","java","python","aws","behavioral","general"]
    docs: list[dict] = []
    for t in topics:
        try:
            col   = memory._get_or_create_collection(t)
            count = col.count()
            if count == 0:
                continue
            result = col.get(limit=min(count,3000), include=["documents","metadatas","ids"])
            for doc_id, content, meta in zip(result["ids"], result["documents"], result["metadatas"]):
                docs.append({"id": doc_id, "content": content, "metadata": meta or {}})
        except Exception as e:
            logger.warning(f"BM25 fetch failed for {t}: {e}")

    bm25 = BM25()
    bm25.index(docs)
    _bm25_index = bm25
    _bm25_topic = topic
    logger.info(f"BM25 index: {len(docs)} docs, topic={topic}")
    return bm25


def invalidate_bm25_cache():
    global _bm25_index
    _bm25_index = None
    logger.info("BM25 cache invalidated")


# ── Confidence scoring ────────────────────────────────────────────────────────
def _confidence(scores: list[float], chunks: list[dict]) -> float:
    if scores and scores[0] != 1.0:
        top3 = scores[:3]
        return sum(1/(1+math.exp(-s)) for s in top3) / len(top3)
    raw = [c.get("score",0) for c in chunks[:3]]
    return sum(raw) / max(len(raw), 1)


# ── Citation builder ──────────────────────────────────────────────────────────
def build_citations(chunks: list[dict]) -> str:
    seen, lines = set(), []
    for i, chunk in enumerate(chunks, 1):
        meta    = chunk.get("metadata",{})
        source  = meta.get("source_path","").split("/")[-1] or "notes"
        hpath   = meta.get("heading_path", meta.get("heading",""))
        key     = f"{source}:{hpath}"
        if key not in seen:
            seen.add(key)
            lines.append(f"[{i}] {source} → {hpath}" if hpath else f"[{i}] {source}")
    return "\n".join(lines)


# ── Main pipeline ─────────────────────────────────────────────────────────────
async def retrieve(
    query: str,
    topic: Optional[str]       = None,
    k_final: int               = 5,
    conversation_history: list[dict] = None,
    use_reranker: bool         = True,
    use_query_rewrite: bool    = True,
) -> tuple[list[dict], str, float]:
    """Returns (chunks, rewritten_query, confidence_score)."""
    from app.services.memory_service import MemoryService
    memory = MemoryService()

    rewritten       = await rewrite_query(query, conversation_history) if use_query_rewrite else query
    detected_topic  = topic or classify_intent(rewritten)

    dense_task = memory.search(rewritten, topic=detected_topic, k=20)
    bm25_task  = _get_bm25_index(detected_topic)
    dense_results, bm25_index = await asyncio.gather(dense_task, bm25_task)
    bm25_results = bm25_index.search(rewritten, k=20)

    fused = reciprocal_rank_fusion(dense_results, bm25_results, top_n=20)
    if not fused:
        return [], rewritten, 0.0

    final, scores = rerank(rewritten, fused, top_k=k_final) if use_reranker else (fused[:k_final], [c.get("score",0) for c in fused[:k_final]])
    confidence = _confidence(scores, final)

    logger.info(
        f"Retrieval: dense={len(dense_results)} bm25={len(bm25_results)} "
        f"fused={len(fused)} final={len(final)} confidence={confidence:.2f} topic={detected_topic}"
    )
    return final, rewritten, confidence


async def build_context(
    query: str,
    topic: Optional[str]       = None,
    conversation_history: list[dict] = None,
) -> tuple[str, str, float, list[dict]]:
    """Returns (context_string, rewritten_query, confidence, chunks)."""
    chunks, rewritten, confidence = await retrieve(
        query, topic=topic, conversation_history=conversation_history
    )

    if not chunks or confidence < CONFIDENCE_THRESHOLD:
        note = (
            f"\n\n⚠️ Retrieval confidence low ({confidence:.0%}). "
            "Answer from general knowledge — not from your personal notes."
        ) if confidence < CONFIDENCE_THRESHOLD else ""
        return note, rewritten, confidence, []

    citations = build_citations(chunks)
    lines = [
        "--- Retrieved context (semantic chunks, reranked) ---",
        f"Sources:\n{citations}", "",
    ]
    for i, chunk in enumerate(chunks, 1):
        meta   = chunk.get("metadata",{})
        hpath  = meta.get("heading_path", meta.get("heading","?"))
        ctype  = meta.get("chunk_type","text")
        source = meta.get("source_path","").split("/")[-1]
        diff   = meta.get("difficulty","")
        dstr   = f" | difficulty={diff}" if diff and diff != "unknown" else ""
        lines.append(f"\n[{i}] {hpath} | type={ctype}{dstr} | {source}")
        lines.append(chunk["content"])
    lines.append("--- End context ---")
    lines.append(
        "\nCite sources inline using [1][2] etc. "
        "If info is missing say: 'Not in your notes — from general knowledge:'"
    )
    return "\n".join(lines), rewritten, confidence, chunks
