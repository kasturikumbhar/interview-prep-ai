from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
import uuid


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Session"
    topic: Optional[str] = None
    mode: str = "chat"
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    topic: Optional[str] = None
    mode: str = "chat"
    model: Optional[str] = None
    use_rag: bool = True


class ChatResponse(BaseModel):
    session_id: str
    message: Message
    sources: list[dict] = Field(default_factory=list)
    model_used: str
