"""
Memory service — ChromaDB-backed RAG pipeline.
One collection per topic for fast filtered retrieval.
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.memory import MemoryChunk, TopicType
from app.services.llm_service import LLMService

settings = get_settings()
logger = get_logger(__name__)

TOPICS = ["dsa", "system_design", "java", "python", "aws", "behavioral", "projects", "general"]


class MemoryService:
    def __init__(self):
        self._client: Optional[chromadb.PersistentClient] = None
        self._llm = LLMService()

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _collection_name(self, topic: str) -> str:
        return f"{settings.CHROMA_COLLECTION_PREFIX}_{topic}"

    def _get_or_create_collection(self, topic: str):
        return self.client.get_or_create_collection(
            name=self._collection_name(topic),
            metadata={"hnsw:space": "cosine"},
        )

    async def ingest(self, chunk: MemoryChunk) -> str:
        embedding = await self._llm.embed(chunk.content)
        collection = self._get_or_create_collection(chunk.topic)
        collection.upsert(
            ids=[chunk.id],
            embeddings=[embedding],
            documents=[chunk.content],
            metadatas=[{
                "topic": chunk.topic,
                "source": chunk.source,
                "source_path": chunk.source_path or "",
                "tags": ",".join(chunk.tags),
                "created_at": chunk.created_at.isoformat(),
            }],
        )
        logger.info(f"Ingested chunk {chunk.id} → topic={chunk.topic}")
        return chunk.id

    async def search(self, query: str, topic: Optional[TopicType] = None, k: int = 5) -> list[dict]:
        embedding = await self._llm.embed(query)

        collections_to_search = (
            [self._get_or_create_collection(topic)]
            if topic
            else [self._get_or_create_collection(t) for t in TOPICS]
        )

        results = []
        for collection in collections_to_search:
            try:
                count = collection.count()
                if count == 0:
                    continue
                resp = collection.query(
                    query_embeddings=[embedding],
                    n_results=min(k, count),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    resp["documents"][0],
                    resp["metadatas"][0],
                    resp["distances"][0],
                ):
                    results.append({
                        "content": doc,
                        "metadata": meta,
                        "score": round(1 - dist, 4),
                    })
            except Exception as e:
                logger.warning(f"Search failed for {collection.name}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]

    def collection_stats(self) -> dict:
        stats = {}
        for topic in TOPICS:
            try:
                col = self._get_or_create_collection(topic)
                stats[topic] = col.count()
            except Exception:
                stats[topic] = 0
        return stats

    async def build_context(self, query: str, topic: Optional[str] = None) -> str:
        chunks = await self.search(query, topic=topic, k=settings.DEFAULT_RETRIEVAL_K)
        if not chunks:
            return ""
        lines = ["--- Context from your personal notes and solutions ---"]
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            source_file = meta.get("source_path", "unknown").split("/")[-1]
            lines.append(f"\n[{i}] File: {source_file} | Topic: {meta.get('topic')} | Relevance: {chunk['score']}")
            lines.append(chunk["content"])
        lines.append("\n--- End of personal context ---")
        return "\n".join(lines)
