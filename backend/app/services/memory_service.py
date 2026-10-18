"""
Memory service — ChromaDB with rich per-chunk metadata.
Stores heading_path, chunk_id, difficulty, chunk_type so retrieval
and RRF can use them for filtering and citation generation.
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.memory import MemoryChunk, TopicType
from app.services.llm_service import LLMService

settings = get_settings()
logger   = get_logger(__name__)

TOPICS = ["dsa","system_design","java","python","aws","behavioral","projects","general"]


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
        embedding  = await self._llm.embed(chunk.content)
        collection = self._get_or_create_collection(chunk.topic)

        # All semantic fields stored as Chroma metadata
        metadata = {
            "topic":          chunk.topic,
            "source":         chunk.source,
            "source_path":    chunk.source_path or "",
            "tags":           ",".join(chunk.tags),
            "created_at":     chunk.created_at.isoformat(),
            # Rich fields from SemanticChunk.to_chroma_metadata()
            "heading":        chunk.metadata.get("heading", ""),
            "parent_heading": chunk.metadata.get("parent_heading", ""),
            "heading_path":   chunk.metadata.get("heading_path", ""),
            "chunk_id":       chunk.metadata.get("chunk_id", chunk.id),
            "document_id":    chunk.metadata.get("document_id", ""),
            "difficulty":     chunk.metadata.get("difficulty", "unknown"),
            "chunk_type":     chunk.metadata.get("chunk_type", "text"),
            "subcategory":    chunk.metadata.get("subcategory", ""),
        }

        collection.upsert(
            ids=[chunk.id],
            embeddings=[embedding],
            documents=[chunk.content],
            metadatas=[metadata],
        )
        return chunk.id

    async def search(
        self,
        query: str,
        topic: Optional[TopicType] = None,
        k: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        embedding = await self._llm.embed(query)

        collections = (
            [self._get_or_create_collection(topic)]
            if topic
            else [self._get_or_create_collection(t) for t in TOPICS]
        )

        results = []
        for col in collections:
            try:
                count = col.count()
                if count == 0:
                    continue
                kwargs = dict(
                    query_embeddings=[embedding],
                    n_results=min(k, count),
                    include=["documents", "metadatas", "distances"],
                )
                if where:
                    kwargs["where"] = where
                resp = col.query(**kwargs)
                for doc, meta, dist in zip(
                    resp["documents"][0],
                    resp["metadatas"][0],
                    resp["distances"][0],
                ):
                    results.append({
                        "content":  doc,
                        "metadata": meta,
                        "score":    round(1 - dist, 4),
                    })
            except Exception as e:
                logger.warning(f"Search failed for {col.name}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]

    def collection_stats(self) -> dict:
        stats = {}
        for topic in TOPICS:
            try:
                stats[topic] = self._get_or_create_collection(topic).count()
            except Exception:
                stats[topic] = 0
        return stats
