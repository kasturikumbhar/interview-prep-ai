from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
import uuid

PersonaType = Literal["dsa", "system_design", "java", "python", "aws", "behavioral"]


class InterviewSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona: PersonaType
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    messages: list[dict] = Field(default_factory=list)
    score: Optional[int] = None
    weaknesses: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InterviewStartRequest(BaseModel):
    persona: PersonaType
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    topic_hint: Optional[str] = None


class InterviewAnswerRequest(BaseModel):
    session_id: str
    answer: str
