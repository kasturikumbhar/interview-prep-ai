import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.chat import Session

settings = get_settings()
logger = get_logger(__name__)


class SessionRepository:
    def __init__(self):
        self.base_dir = Path(settings.SESSIONS_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def save(self, session: Session) -> None:
        session.updated_at = datetime.utcnow()
        with open(self._path(session.id), "w") as f:
            json.dump(session.model_dump(mode="json"), f, indent=2, default=str)

    def load(self, session_id: str) -> Optional[Session]:
        p = self._path(session_id)
        if not p.exists():
            return None
        with open(p) as f:
            return Session(**json.load(f))

    def list_sessions(self, limit: int = 50) -> list[dict]:
        sessions = []
        for path in sorted(self.base_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                with open(path) as f:
                    data = json.load(f)
                sessions.append({
                    "id": data["id"],
                    "title": data.get("title", "Untitled"),
                    "topic": data.get("topic"),
                    "mode": data.get("mode", "chat"),
                    "message_count": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at"),
                })
            except Exception as e:
                logger.warning(f"Could not load session {path.name}: {e}")
            if len(sessions) >= limit:
                break
        return sessions

    def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if p.exists():
            p.unlink()
            return True
        return False
