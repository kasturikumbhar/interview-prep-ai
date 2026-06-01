from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from app.services.interview_service import (
    start_interview, answer_question, generate_report, extract_resume
)
from app.repositories.interview_repository import (
    InterviewRepository, ResumeRepository, StoryRepository, RevisionRepository
)

router = APIRouter(prefix="/interview", tags=["interview"])
interview_repo = InterviewRepository()
resume_repo = ResumeRepository()
story_repo = StoryRepository()
revision_repo = RevisionRepository()

TopicType = Literal["dsa", "system_design", "java", "python", "aws", "behavioral"]
DifficultyType = Literal["easy", "medium", "hard"]


class StartRequest(BaseModel):
    topic: TopicType
    difficulty: DifficultyType = "medium"


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class ResumeUploadRequest(BaseModel):
    text: str


class StoryRequest(BaseModel):
    title: str
    situation: str
    task: str
    action: str
    result: str
    tags: list[str] = []
    star_score: Optional[int] = None


class RevisionUpdateRequest(BaseModel):
    item_id: int
    confidence: int  # 1-5


# ── Interview ─────────────────────────────────────────────────────────────────

@router.post("/start")
async def start(req: StartRequest):
    return await start_interview(req.topic, req.difficulty)


@router.post("/answer")
async def answer(req: AnswerRequest):
    try:
        return await answer_question(req.session_id, req.answer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/report/{session_id}")
async def get_report(session_id: str):
    try:
        return await generate_report(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/report/{session_id}")
async def get_cached_report(session_id: str):
    report = interview_repo.get_report(session_id)
    if not report:
        # Generate it
        try:
            return await generate_report(session_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return report


@router.get("/sessions")
async def list_sessions():
    return interview_repo.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = interview_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    qa = interview_repo.get_session_qa(session_id)
    return {**session, "qa": qa}


# ── Resume ────────────────────────────────────────────────────────────────────

@router.post("/resume/upload")
async def upload_resume(req: ResumeUploadRequest):
    if len(req.text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Resume text too short")
    return await extract_resume(req.text)


@router.get("/resume")
async def get_resume():
    resume = resume_repo.get()
    if not resume:
        return {"message": "No resume uploaded yet"}
    return resume


# ── Story Bank ────────────────────────────────────────────────────────────────

@router.post("/stories")
async def add_story(req: StoryRequest):
    story_id = story_repo.add(
        title=req.title,
        situation=req.situation,
        task=req.task,
        action=req.action,
        result=req.result,
        tags=req.tags,
        star_score=req.star_score,
    )
    return {"id": story_id, "title": req.title}


@router.get("/stories")
async def get_stories():
    return story_repo.get_all()


@router.get("/stories/search")
async def search_stories(q: str):
    return story_repo.search(q)


@router.delete("/stories/{story_id}")
async def delete_story(story_id: int):
    story_repo.delete(story_id)
    return {"deleted": story_id}


# ── Spaced Repetition Revision ────────────────────────────────────────────────

@router.get("/revision/today")
async def revision_today():
    items = revision_repo.get_due_today(limit=20)
    return {"items": items, "count": len(items)}


@router.get("/revision/all")
async def revision_all(topic: Optional[str] = None):
    return {"items": revision_repo.get_all(topic)}


@router.post("/revision/update")
async def update_revision(req: RevisionUpdateRequest):
    if not 1 <= req.confidence <= 5:
        raise HTTPException(status_code=400, detail="confidence must be 1-5")
    revision_repo.update_review(req.item_id, req.confidence)
    return {"updated": req.item_id, "confidence": req.confidence}
