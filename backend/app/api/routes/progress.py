from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.progress_service import (
    get_dsa_progress, get_pattern_gaps, get_all_topic_mastery,
    get_revision_candidates, get_what_to_study_today, generate_study_plan,
)
from app.repositories.progress_repository import ProgressRepository

router = APIRouter(prefix="/progress", tags=["progress"])
repo = ProgressRepository()


class ProblemRequest(BaseModel):
    problem_name: str
    pattern: Optional[str] = None
    difficulty: Optional[str] = None
    status: str = "solved"
    language: str = "python"
    leetcode_number: Optional[int] = None
    time_complexity: Optional[str] = None
    notes: Optional[str] = None


@router.get("/dsa")
async def get_dsa():
    return get_dsa_progress()


@router.get("/mastery")
async def get_mastery():
    """Mastery levels across ALL topics from KB files."""
    return get_all_topic_mastery()


@router.get("/summary")
async def get_summary():
    """Full summary — DSA + all topic mastery."""
    dsa = get_dsa_progress()
    mastery = get_all_topic_mastery()
    return {**dsa, "mastery_by_topic": mastery}


@router.get("/gaps")
async def get_gaps():
    return get_pattern_gaps()


@router.get("/weaknesses")
async def get_weaknesses():
    kb_weaknesses = repo.get_all_weaknesses()
    session_weaknesses = repo.get_aggregated_weaknesses_from_sessions()
    scores = repo.get_avg_score_by_topic()
    return {
        "kb_weaknesses": kb_weaknesses,
        "session_weaknesses": [{"topic": w, "count": c} for w, c in session_weaknesses],
        "avg_scores_by_topic": scores,
    }


@router.get("/today")
async def what_to_study_today():
    return get_what_to_study_today()


@router.get("/revision")
async def get_revision_queue():
    return {"candidates": get_revision_candidates()}


@router.get("/plan")
async def get_study_plan(days: int = 7):
    return await generate_study_plan(days)


@router.post("/problem")
async def add_problem(req: ProblemRequest):
    pid = repo.upsert_problem(
        problem_name=req.problem_name,
        pattern=req.pattern,
        difficulty=req.difficulty,
        status=req.status,
        language=req.language,
        leetcode_number=req.leetcode_number,
        time_complexity=req.time_complexity,
        notes=req.notes,
    )
    return {"id": pid, "problem": req.problem_name}


@router.post("/problem/{problem_name}/revise")
async def mark_revised(problem_name: str):
    repo.increment_revision(problem_name)
    return {"revised": problem_name}


@router.get("/problems")
async def list_problems(pattern: Optional[str] = None):
    if pattern:
        return repo.get_problems_by_pattern(pattern)
    return repo.get_all_problems()


@router.get("/roadmap")
async def get_roadmap():
    return {"items": repo.get_roadmap_items()}
