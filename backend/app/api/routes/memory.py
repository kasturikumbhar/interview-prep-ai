from fastapi import APIRouter
from app.models.memory import IngestRequest, SearchRequest, MemoryChunk
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])
memory_service = MemoryService()


@router.post("/ingest")
async def ingest(req: IngestRequest):
    chunk = MemoryChunk(content=req.content, topic=req.topic, source=req.source, source_path=req.source_path, tags=req.tags)
    chunk_id = await memory_service.ingest(chunk)
    return {"id": chunk_id, "topic": req.topic}


@router.post("/search")
async def search(req: SearchRequest):
    results = await memory_service.search(req.query, topic=req.topic, k=req.k)
    return {"results": results, "count": len(results)}


@router.get("/stats")
async def stats():
    return memory_service.collection_stats()
