from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from app.services.analysis_service import (
    analyze_weakness, score_star_answer,
    generate_revision_questions, detect_dsa_patterns,
)
from app.repositories.stats_repository import StatsRepository
from app.repositories.session_repository import SessionRepository
from app.services.memory_service import MemoryService
from app.core.config import get_settings

router = APIRouter(prefix="/analysis", tags=["analysis"])
stats_repo = StatsRepository()
session_repo = SessionRepository()
memory_service = MemoryService()
settings = get_settings()


class WeaknessRequest(BaseModel):
    session_id: str


class StarRequest(BaseModel):
    question: str
    answer: str


class RevisionRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5


class PatternRequest(BaseModel):
    topic: str = "dsa"


@router.post("/weakness")
async def analyze_session_weakness(req: WeaknessRequest):
    session = session_repo.load(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if len(session.messages) < 2:
        raise HTTPException(status_code=400, detail="Session too short to analyze")
    conversation = [
        {"role": m.role, "content": m.content}
        for m in session.messages if m.role in ("user", "assistant")
    ]
    report = await analyze_weakness(conversation)
    stats_repo.save_weakness_report(req.session_id, session.topic, report)
    stats_repo.record_activity(session.topic)
    return report


@router.get("/weakness/history")
async def get_weakness_history():
    return stats_repo.get_weakness_history()


@router.get("/weakness/summary")
async def get_weakness_summary():
    return stats_repo.get_aggregated_weaknesses()


@router.post("/star")
async def score_star(req: StarRequest):
    if len(req.answer.strip()) < 30:
        raise HTTPException(status_code=400, detail="Answer too short")
    result = await score_star_answer(req.question, req.answer)
    stats_repo.save_star_score(req.question, req.answer, result)
    return result


@router.get("/star/history")
async def get_star_history():
    return stats_repo.get_star_history()


@router.get("/star/stats")
async def get_star_stats():
    return stats_repo.get_star_stats()


@router.post("/revision")
async def get_revision_questions(req: RevisionRequest):
    """
    Generate senior-level revision questions grounded in the user's KB content.
    Uses ChromaDB to pull actual content from notes, not generic questions.
    """
    # Pull rich content from ChromaDB — more chunks for better coverage
    query = f"concepts patterns techniques explained {req.topic or 'software engineering interview'}"
    chunks = await memory_service.search(query, topic=req.topic, k=12)

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No notes found for topic '{req.topic}'. Run ingestion first."
        )

    # Filter for substantive chunks (not just file headers or short snippets)
    good_chunks = [
        c for c in chunks
        if len(c["content"]) > 150 and c["score"] > 0.3
    ]
    if not good_chunks:
        good_chunks = chunks

    combined = "\n\n---\n\n".join(c["content"] for c in good_chunks[:10])
    questions = await generate_revision_questions(combined, count=req.count)

    return {
        "questions": questions,
        "topic": req.topic,
        "source_chunks": len(good_chunks),
        "note": "Questions generated from your personal knowledge base content"
    }


@router.post("/patterns")
async def detect_patterns(req: PatternRequest):
    notes_dir = Path(settings.NOTES_DIR) / req.topic
    if not notes_dir.exists():
        raise HTTPException(status_code=404, detail=f"No notes at data/notes/{req.topic}")

    files_content = {}
    for path in notes_dir.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".java", ".md", ".txt"}:
            try:
                files_content[path.name] = path.read_text(encoding="utf-8")
            except Exception:
                continue

    if not files_content:
        raise HTTPException(status_code=404, detail="No files found")

    return await detect_dsa_patterns(files_content)


@router.get("/dashboard")
async def get_dashboard():
    return stats_repo.get_dashboard()
