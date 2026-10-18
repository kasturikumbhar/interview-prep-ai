"""
Analysis routes — STAR scoring, weakness analysis, revision questions,
due-today generation, pattern detection, dashboard.

Self-contained: all imports explicit, no missing deps.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

router   = APIRouter(prefix="/analysis", tags=["analysis"])
settings = get_settings()
logger   = get_logger(__name__)


# ── Lazy imports to avoid circular deps ──────────────────────────────────────
def _analysis_svc():
    from app.services.analysis_service import (
        analyze_weakness, score_star_answer,
        generate_revision_questions, generate_question_for_subtopic,
        detect_dsa_patterns,
    )
    return analyze_weakness, score_star_answer, generate_revision_questions, \
           generate_question_for_subtopic, detect_dsa_patterns

def _stats_repo():
    from app.repositories.stats_repository import StatsRepository
    return StatsRepository()

def _session_repo():
    from app.repositories.session_repository import SessionRepository
    return SessionRepository()

def _revision_repo():
    from app.repositories.interview_repository import RevisionRepository
    return RevisionRepository()

def _memory_svc():
    from app.services.memory_service import MemoryService
    return MemoryService()


# ── Request models ────────────────────────────────────────────────────────────
class WeaknessRequest(BaseModel):
    session_id: str

class StarRequest(BaseModel):
    question: str
    answer: str

class RevisionRequest(BaseModel):
    topic: Optional[str] = "dsa"
    count: int = 5

class DueTodayRequest(BaseModel):
    limit: int = 10

class PatternRequest(BaseModel):
    topic: str = "dsa"


# ── Weakness analysis ─────────────────────────────────────────────────────────
@router.post("/weakness")
async def analyze_session_weakness(req: WeaknessRequest):
    analyze_weakness, *_ = _analysis_svc()
    session = _session_repo().load(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if len(session.messages) < 2:
        raise HTTPException(status_code=400, detail="Session too short to analyze")

    conversation = [
        {"role": m.role, "content": m.content}
        for m in session.messages
        if m.role in ("user", "assistant")
    ]
    report = await analyze_weakness(conversation)

    stats = _stats_repo()
    stats.save_weakness_report(req.session_id, session.topic, report)
    stats.record_activity(session.topic)
    return report


@router.get("/weakness/history")
async def get_weakness_history():
    return _stats_repo().get_weakness_history()


@router.get("/weakness/summary")
async def get_weakness_summary():
    return _stats_repo().get_aggregated_weaknesses()


# ── STAR scoring ──────────────────────────────────────────────────────────────
@router.post("/star")
async def score_star(req: StarRequest):
    if len(req.answer.strip()) < 30:
        raise HTTPException(status_code=400, detail="Answer too short")
    _, score_star_answer, *_ = _analysis_svc()
    result = await score_star_answer(req.question, req.answer)
    stats  = _stats_repo()
    stats.save_star_score(req.question, req.answer, result)
    return result


@router.get("/star/history")
async def get_star_history():
    return _stats_repo().get_star_history()

@router.get("/star/stats")
async def get_star_stats():
    return _stats_repo().get_star_stats()


# ── Revision question generation ──────────────────────────────────────────────
@router.post("/revision")
async def get_revision_questions(req: RevisionRequest):
    """
    LLM knowledge + KB context → senior-level interview questions.
    KB chunks give topic hints; LLM generates real interview-quality questions.
    """
    _, _, generate_revision_questions, *_ = _analysis_svc()
    memory = _memory_svc()

    query  = f"{req.topic or 'software engineering'} concepts patterns techniques"
    chunks = await memory.search(query, topic=req.topic, k=10)

    content = ""
    if chunks:
        good    = [c for c in chunks if len(c["content"]) > 100]
        content = "\n\n".join(c["content"] for c in (good or chunks)[:8])

    questions = await generate_revision_questions(
        content=content,
        count=req.count,
        topic=req.topic or "dsa",
    )

    return {
        "questions":     questions,
        "topic":         req.topic,
        "source_chunks": len(chunks),
    }


# ── Due-today → proper interview questions ────────────────────────────────────
@router.post("/revision/due-today-questions")
async def due_today_as_questions(req: DueTodayRequest):
    """
    Convert spaced-repetition due items into real interview questions.
    Each subtopic → LLM generates a full question with hint + answer points.
    """
    _, _, _, generate_question_for_subtopic, _ = _analysis_svc()
    revision = _revision_repo()
    due      = revision.get_due_today(limit=req.limit)

    if not due:
        return {"questions": [], "count": 0, "message": "Nothing due today"}

    questions = []
    for item in due:
        topic    = item.get("topic", "general")
        subtopic = item.get("subtopic", "")
        if not subtopic or len(subtopic.strip()) < 3:
            continue
        q = await generate_question_for_subtopic(topic, subtopic)
        if q:
            q["revision_item_id"] = item["id"]
            q["confidence_score"] = item.get("confidence_score", 3)
            q["review_count"]     = item.get("review_count", 0)
            questions.append(q)

    return {"questions": questions, "count": len(questions), "items_processed": len(due)}


# ── DSA pattern detection ─────────────────────────────────────────────────────
@router.post("/patterns")
async def detect_patterns(req: PatternRequest):
    *_, detect_dsa_patterns = _analysis_svc()
    notes_dir = Path(settings.NOTES_DIR) / req.topic
    if not notes_dir.exists():
        raise HTTPException(
            status_code=404, detail=f"No notes at data/notes/{req.topic}"
        )
    files_content: dict[str, str] = {}
    for p in notes_dir.rglob("*"):
        if p.is_file() and p.suffix in {".py", ".java", ".md", ".txt"}:
            try:
                files_content[p.name] = p.read_text(encoding="utf-8")
            except Exception:
                continue
    if not files_content:
        raise HTTPException(status_code=404, detail="No files found")
    return await detect_dsa_patterns(files_content)


# ── Evaluation endpoint ───────────────────────────────────────────────────────
@router.post("/evaluate")
async def run_eval(k: int = 5):
    """
    Run the RAG evaluation harness.
    Returns hit_rate, MRR, context_precision, avg_latency_ms.
    """
    try:
        from app.services.evaluation import run_evaluation
        results = await run_evaluation(k=k)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Dashboard ─────────────────────────────────────────────────────────────────
@router.get("/dashboard")
async def get_dashboard():
    try:
        return _stats_repo().get_dashboard()
    except Exception as e:
        logger.warning(f"Dashboard fetch failed: {e}")
        return {}
