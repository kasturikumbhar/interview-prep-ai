from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from app.services.analysis_service import (
    analyze_weakness, score_star_answer,
    generate_revision_questions, generate_question_for_subtopic,
    detect_dsa_patterns,
)
from app.repositories.stats_repository import StatsRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.interview_repository import RevisionRepository
from app.services.memory_service import MemoryService
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/analysis", tags=["analysis"])
stats_repo = StatsRepository()
session_repo = SessionRepository()
revision_repo = RevisionRepository()
memory_service = MemoryService()
settings = get_settings()
logger = get_logger(__name__)


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


class DueTodayQuestionsRequest(BaseModel):
    limit: int = 10


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
    Generate senior-level questions using LLM knowledge + KB context.
    KB content gives topic hints; LLM generates real interview questions.
    """
    # Get KB content as context (what topics the candidate has studied)
    query = f"{req.topic or 'software engineering'} concepts patterns techniques"
    chunks = await memory_service.search(query, topic=req.topic, k=10)

    # Use content as topic context, not as question source
    content = ""
    if chunks:
        good = [c for c in chunks if len(c["content"]) > 100]
        content = "\n\n".join(c["content"] for c in (good or chunks)[:8])

    questions = await generate_revision_questions(
        content=content,
        count=req.count,
        topic=req.topic or "dsa",
    )

    return {
        "questions": questions,
        "topic": req.topic,
        "source_chunks": len(chunks),
        "note": "Questions generated using LLM knowledge + your KB as context"
    }


@router.post("/revision/due-today-questions")
async def get_due_today_as_questions(req: DueTodayQuestionsRequest):
    """
    Convert due-today revision items into proper interview questions with hints.
    Generates questions using LLM knowledge about each subtopic.
    """
    due_items = revision_repo.get_due_today(limit=req.limit)

    if not due_items:
        return {"questions": [], "count": 0, "message": "Nothing due today"}

    questions = []
    for item in due_items:
        topic = item.get("topic", "general")
        subtopic = item.get("subtopic", "")

        if not subtopic or len(subtopic.strip()) < 3:
            continue

        q = await generate_question_for_subtopic(topic, subtopic)
        if q:
            q["revision_item_id"] = item["id"]
            q["confidence_score"] = item.get("confidence_score", 3)
            q["review_count"] = item.get("review_count", 0)
            questions.append(q)

    return {
        "questions": questions,
        "count": len(questions),
        "items_processed": len(due_items),
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
