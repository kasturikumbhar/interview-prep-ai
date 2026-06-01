import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)
DB_PATH = Path(settings.DATA_DIR) / "progress.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_interview_tables():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                difficulty TEXT DEFAULT 'medium',
                resume_context TEXT,
                status TEXT DEFAULT 'active',
                final_report TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                ended_at TEXT
            );

            CREATE TABLE IF NOT EXISTS interview_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                question_text TEXT NOT NULL,
                question_number INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES interview_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS interview_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                question_id INTEGER NOT NULL,
                answer_text TEXT NOT NULL,
                score INTEGER,
                feedback TEXT,
                follow_up TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES interview_sessions(id),
                FOREIGN KEY (question_id) REFERENCES interview_questions(id)
            );

            CREATE TABLE IF NOT EXISTS resume_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT,
                skills TEXT,
                projects TEXT,
                technologies TEXT,
                achievements TEXT,
                uploaded_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS behavioral_stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                situation TEXT,
                task TEXT,
                action TEXT,
                result TEXT,
                tags TEXT,
                star_score INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS revision_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                subtopic TEXT,
                content TEXT,
                difficulty TEXT DEFAULT 'medium',
                confidence_score INTEGER DEFAULT 3,
                review_count INTEGER DEFAULT 0,
                last_reviewed TEXT,
                next_review_date TEXT,
                source_file TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
    logger.info("Interview tables initialized")


init_interview_tables()


class InterviewRepository:

    def create_session(self, session_id: str, topic: str, difficulty: str, resume_context: str = "") -> dict:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO interview_sessions (id, topic, difficulty, resume_context)
                VALUES (?, ?, ?, ?)
            """, (session_id, topic, difficulty, resume_context))
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[dict]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def add_question(self, session_id: str, question_text: str, question_number: int) -> int:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO interview_questions (session_id, question_text, question_number)
                VALUES (?, ?, ?)
            """, (session_id, question_text, question_number))
            return cur.lastrowid

    def add_answer(self, session_id: str, question_id: int, answer_text: str,
                   score: int, feedback: str, follow_up: str) -> int:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO interview_answers (session_id, question_id, answer_text, score, feedback, follow_up)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, question_id, answer_text, score, feedback, follow_up))
            return cur.lastrowid

    def get_session_qa(self, session_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT q.id as question_id, q.question_text, q.question_number,
                       a.answer_text, a.score, a.feedback, a.follow_up, a.created_at
                FROM interview_questions q
                LEFT JOIN interview_answers a ON a.question_id = q.id
                WHERE q.session_id = ?
                ORDER BY q.question_number
            """, (session_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_latest_question(self, session_id: str) -> Optional[dict]:
        with get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM interview_questions
                WHERE session_id = ?
                ORDER BY question_number DESC LIMIT 1
            """, (session_id,)).fetchone()
            return dict(row) if row else None

    def get_question_count(self, session_id: str) -> int:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM interview_questions WHERE session_id=?", (session_id,)
            ).fetchone()
            return row["c"]

    def end_session(self, session_id: str, report: dict):
        with get_conn() as conn:
            conn.execute("""
                UPDATE interview_sessions
                SET status='ended', final_report=?, ended_at=datetime('now')
                WHERE id=?
            """, (json.dumps(report), session_id))

    def get_report(self, session_id: str) -> Optional[dict]:
        session = self.get_session(session_id)
        if not session:
            return None
        report_raw = session.get("final_report")
        if report_raw:
            try:
                return json.loads(report_raw)
            except Exception:
                pass
        return None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT s.*, COUNT(q.id) as question_count
                FROM interview_sessions s
                LEFT JOIN interview_questions q ON q.session_id = s.id
                GROUP BY s.id ORDER BY s.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]


class ResumeRepository:

    def save(self, raw_text: str, skills: list, projects: list,
             technologies: list, achievements: list) -> int:
        with get_conn() as conn:
            # Only keep latest
            conn.execute("DELETE FROM resume_data")
            cur = conn.execute("""
                INSERT INTO resume_data (raw_text, skills, projects, technologies, achievements)
                VALUES (?, ?, ?, ?, ?)
            """, (raw_text, json.dumps(skills), json.dumps(projects),
                  json.dumps(technologies), json.dumps(achievements)))
            return cur.lastrowid

    def get(self) -> Optional[dict]:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM resume_data ORDER BY uploaded_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            for key in ("skills", "projects", "technologies", "achievements"):
                try:
                    d[key] = json.loads(d.get(key) or "[]")
                except Exception:
                    d[key] = []
            return d

    def get_context_string(self) -> str:
        resume = self.get()
        if not resume:
            return ""
        parts = []
        if resume.get("skills"):
            parts.append(f"Skills: {', '.join(resume['skills'][:15])}")
        if resume.get("technologies"):
            parts.append(f"Technologies: {', '.join(resume['technologies'][:15])}")
        if resume.get("projects"):
            parts.append(f"Projects: {'; '.join(resume['projects'][:5])}")
        if resume.get("achievements"):
            parts.append(f"Achievements: {'; '.join(resume['achievements'][:3])}")
        return "\n".join(parts)


class StoryRepository:

    def add(self, title: str, situation: str, task: str, action: str,
            result: str, tags: list, star_score: int = None) -> int:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO behavioral_stories (title, situation, task, action, result, tags, star_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, situation, task, action, result, json.dumps(tags), star_score))
            return cur.lastrowid

    def get_all(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM behavioral_stories ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags") or "[]")
                except Exception:
                    d["tags"] = []
                result.append(d)
            return result

    def search(self, query: str) -> list[dict]:
        query_lower = f"%{query.lower()}%"
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM behavioral_stories
                WHERE lower(title) LIKE ? OR lower(tags) LIKE ?
                OR lower(situation) LIKE ? OR lower(action) LIKE ?
                ORDER BY created_at DESC
            """, (query_lower, query_lower, query_lower, query_lower)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags") or "[]")
                except Exception:
                    d["tags"] = []
                result.append(d)
            return result

    def get_relevant_for_topic(self, topic: str) -> list[dict]:
        topic_lower = f"%{topic.lower()}%"
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM behavioral_stories
                WHERE lower(tags) LIKE ? OR lower(title) LIKE ?
                ORDER BY star_score DESC LIMIT 3
            """, (topic_lower, topic_lower)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags") or "[]")
                except Exception:
                    d["tags"] = []
                result.append(d)
            return result

    def delete(self, story_id: int):
        with get_conn() as conn:
            conn.execute("DELETE FROM behavioral_stories WHERE id=?", (story_id,))


class RevisionRepository:

    def upsert(self, topic: str, subtopic: str, content: str,
               difficulty: str = "medium", source_file: str = "") -> int:
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM revision_items WHERE topic=? AND subtopic=?",
                (topic, subtopic)
            ).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute("""
                INSERT INTO revision_items (topic, subtopic, content, difficulty, source_file)
                VALUES (?, ?, ?, ?, ?)
            """, (topic, subtopic, content, difficulty, source_file))
            return cur.lastrowid

    def update_review(self, item_id: int, confidence: int):
        from datetime import timedelta
        # Spaced repetition intervals: 1,3,7,14,30 days based on confidence
        intervals = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}
        days = intervals.get(confidence, 3)
        next_review = (datetime.utcnow() + timedelta(days=days)).date().isoformat()
        with get_conn() as conn:
            conn.execute("""
                UPDATE revision_items
                SET confidence_score=?, review_count=review_count+1,
                    last_reviewed=datetime('now'), next_review_date=?
                WHERE id=?
            """, (confidence, next_review, item_id))

    def get_due_today(self, limit: int = 20) -> list[dict]:
        today = datetime.utcnow().date().isoformat()
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM revision_items
                WHERE next_review_date <= ? OR next_review_date IS NULL
                ORDER BY
                    CASE WHEN next_review_date IS NULL THEN 0 ELSE 1 END,
                    confidence_score ASC,
                    difficulty DESC
                LIMIT ?
            """, (today, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_all(self, topic: str = None) -> list[dict]:
        with get_conn() as conn:
            if topic:
                rows = conn.execute(
                    "SELECT * FROM revision_items WHERE topic=? ORDER BY next_review_date",
                    (topic,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM revision_items ORDER BY topic, subtopic"
                ).fetchall()
            return [dict(r) for r in rows]
