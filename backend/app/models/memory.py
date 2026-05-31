from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid

TopicType = Literal["dsa", "system_design", "java", "python", "aws", "behavioral", "projects", "general"]


class MemoryChunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    topic: TopicType = "general"
    source: str = "manual"
    source_path: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class IngestRequest(BaseModel):
    content: str
    topic: TopicType
    source: str = "manual"
    source_path: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    topic: Optional[TopicType] = None
    k: int = 5
