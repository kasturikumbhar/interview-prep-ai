"""
Progress Repository — SQLite-backed, multi-topic progress tracking.
Stores DSA problems, mastery levels from KB files, session summaries,
interview scores, and behavioral stories across ALL topics.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional
from contextlib import contextmanager

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

DB_PATH = Path(settings.DATA_DIR) / "progress.db"

ALL_TOPICS = ["dsa", "system_design", "java", "python", "aws", "behavioral", "projects", "general"]

DSA_PATTERNS = [
    "Sliding Window", "Two Pointers", "Fast Slow Pointers",
    "Merge Intervals", "Binary Search", "Tree BFS", "Tree DFS",
    "Graph BFS", "Graph DFS", "Topological Sort", "Backtracking",
    "Heap", "Two Heaps", "Greedy", "Dynamic Programming 1D",
    "Dynamic Programming 2D", "Trie", "Union Find", "Monotonic Stack",
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS dsa_problems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_name TEXT NOT NULL UNIQUE,
                pattern TEXT,
                difficulty TEXT,
                status TEXT DEFAULT 'solved',
                language TEXT DEFAULT 'python',
                source_file TEXT,
                leetcode_number INTEGER,
                time_complexity TEXT,
                space_complexity TEXT,
                notes TEXT,
                revision_count INTEGER DEFAULT 0,
                last_revised TEXT,
                solved_at TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS topic_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_name TEXT NOT NULL,
                category TEXT NOT NULL,
                mastery_score INTEGER DEFAULT 3,
                mastery_label TEXT,
                source_file TEXT,
                notes TEXT,
                last_updated TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(topic_name, category)
            );

            CREATE TABLE IF NOT EXISTS session_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                topic TEXT,
                topics_covered TEXT,
                strengths TEXT,
                weaknesses TEXT,
                next_actions TEXT,
                message_count INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS interview_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                topic TEXT,
                score INTEGER,
                mode TEXT,
                weaknesses TEXT,
                strengths TEXT,
                summary TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS knowledge_base_weaknesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weakness TEXT NOT NULL,
                category TEXT,
                source_file TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS roadmap_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item TEXT NOT NULL,
                category TEXT,
                source_file TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
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
        """)
    logger.info(f"Database initialized at {DB_PATH}")


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


class ProgressRepository:

    def __init__(self):
        init_db()

    # ── DSA Problems ─────────────────────────────────────────────────────────

    def upsert_problem(self, problem_name: str, pattern: str = None,
                       difficulty: str = None, status: str = "solved",
                       language: str = "python", source_file: str = None,
                       leetcode_number: int = None, time_complexity: str = None,
                       space_complexity: str = None, notes: str = None) -> int:
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM dsa_problems WHERE problem_name = ?", (problem_name,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE dsa_problems SET pattern=COALESCE(?,pattern),
                    difficulty=COALESCE(?,difficulty), status=?, language=?,
                    source_file=COALESCE(?,source_file), time_complexity=COALESCE(?,time_complexity),
                    revision_count=revision_count+1, last_revised=datetime('now')
                    WHERE id=?
                """, (pattern, difficulty, status, language, source_file,
                      time_complexity, existing["id"]))
                return existing["id"]
            else:
                cur = conn.execute("""
                    INSERT INTO dsa_problems
                    (problem_name, pattern, difficulty, status, language,
                     source_file, leetcode_number, time_complexity, space_complexity, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (problem_name, pattern, difficulty, status, language,
                      source_file, leetcode_number, time_complexity, space_complexity, notes))
                return cur.lastrowid

    def get_all_problems(self) -> list[dict]:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM dsa_problems ORDER BY created_at DESC"
            ).fetchall()]

    def get_pattern_summary(self) -> dict[str, int]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT pattern, COUNT(*) as count FROM dsa_problems
                WHERE pattern IS NOT NULL AND pattern != ''
                GROUP BY pattern ORDER BY count DESC
            """).fetchall()
            return {r["pattern"]: r["count"] for r in rows}

    def get_difficulty_summary(self) -> dict[str, int]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT difficulty, COUNT(*) as count FROM dsa_problems
                WHERE difficulty IS NOT NULL GROUP BY difficulty
            """).fetchall()
            return {r["difficulty"]: r["count"] for r in rows}

    def get_recently_solved(self, days: int = 7) -> list[dict]:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute("""
                SELECT * FROM dsa_problems
                WHERE created_at >= datetime('now', ?)
                ORDER BY created_at DESC
            """, (f"-{days} days",)).fetchall()]

    def increment_revision(self, problem_name: str):
        with get_conn() as conn:
            conn.execute("""
                UPDATE dsa_problems
                SET revision_count=revision_count+1, last_revised=datetime('now')
                WHERE problem_name=?
            """, (problem_name,))

    def get_problems_by_pattern(self, pattern: str) -> list[dict]:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM dsa_problems WHERE pattern=? ORDER BY created_at DESC",
                (pattern,)
            ).fetchall()]

    # ── Topic Mastery (from KB MD files) ─────────────────────────────────────

    def upsert_topic_mastery(self, topic_name: str, category: str,
                             mastery_score: int, mastery_label: str = "",
                             source_file: str = "", notes: str = ""):
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO topic_mastery (topic_name, category, mastery_score, mastery_label, source_file, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_name, category) DO UPDATE SET
                    mastery_score=excluded.mastery_score,
                    mastery_label=excluded.mastery_label,
                    source_file=excluded.source_file,
                    last_updated=datetime('now')
            """, (topic_name, category, mastery_score, mastery_label, source_file, notes))

    def get_mastery_by_category(self) -> dict[str, list[dict]]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM topic_mastery ORDER BY category, mastery_score DESC
            """).fetchall()
            result: dict[str, list] = {}
            for r in rows:
                cat = r["category"]
                if cat not in result:
                    result[cat] = []
                result[cat].append(dict(r))
            return result

    def get_mastery_summary(self) -> dict[str, dict]:
        """Per-category mastery summary for dashboard."""
        by_cat = self.get_mastery_by_category()
        summary = {}
        for cat, entries in by_cat.items():
            if not entries:
                continue
            scores = [e["mastery_score"] for e in entries]
            strong = [e["topic_name"] for e in entries if e["mastery_score"] >= 4]
            weak = [e["topic_name"] for e in entries if e["mastery_score"] <= 2]
            summary[cat] = {
                "avg_mastery": round(sum(scores) / len(scores), 1),
                "topic_count": len(entries),
                "strong_topics": strong,
                "weak_topics": weak,
                "all_topics": [{"name": e["topic_name"], "score": e["mastery_score"], "label": e["mastery_label"]} for e in entries],
            }
        return summary

    # ── KB Weaknesses ─────────────────────────────────────────────────────────

    def save_kb_weaknesses(self, weaknesses: list[str], category: str, source_file: str):
        with get_conn() as conn:
            for w in weaknesses:
                # Avoid duplicates
                existing = conn.execute(
                    "SELECT id FROM knowledge_base_weaknesses WHERE weakness=? AND category=?",
                    (w, category)
                ).fetchone()
                if not existing:
                    conn.execute("""
                        INSERT INTO knowledge_base_weaknesses (weakness, category, source_file)
                        VALUES (?, ?, ?)
                    """, (w, category, source_file))

    def get_all_weaknesses(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT weakness, category, COUNT(*) as frequency
                FROM knowledge_base_weaknesses
                GROUP BY weakness, category
                ORDER BY frequency DESC
            """).fetchall()
            return [dict(r) for r in rows]

    # ── Roadmap Items ─────────────────────────────────────────────────────────

    def save_roadmap_items(self, items: list[str], category: str, source_file: str):
        with get_conn() as conn:
            for item in items:
                existing = conn.execute(
                    "SELECT id FROM roadmap_items WHERE item=?", (item,)
                ).fetchone()
                if not existing:
                    conn.execute("""
                        INSERT INTO roadmap_items (item, category, source_file)
                        VALUES (?, ?, ?)
                    """, (item, category, source_file))

    def get_roadmap_items(self, status: str = "pending") -> list[dict]:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM roadmap_items WHERE status=? ORDER BY category, created_at",
                (status,)
            ).fetchall()]

    # ── Session Summaries ─────────────────────────────────────────────────────

    def save_session_summary(self, session_id: str, topic: Optional[str],
                             summary: dict, message_count: int):
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO session_summaries
                (session_id, topic, topics_covered, strengths, weaknesses, next_actions, message_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, topic,
                json.dumps(summary.get("topics_covered", [])),
                json.dumps(summary.get("strengths", [])),
                json.dumps(summary.get("weaknesses", [])),
                json.dumps(summary.get("next_actions", [])),
                message_count,
            ))

    def get_recent_summaries(self, limit: int = 5) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM session_summaries ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for key in ("topics_covered", "strengths", "weaknesses", "next_actions"):
                    try:
                        d[key] = json.loads(d.get(key) or "[]")
                    except Exception:
                        d[key] = []
                result.append(d)
            return result

    def get_aggregated_weaknesses_from_sessions(self) -> list[tuple[str, int]]:
        summaries = self.get_recent_summaries(limit=50)
        counts: dict[str, int] = {}
        for s in summaries:
            for w in s.get("weaknesses", []):
                counts[w] = counts.get(w, 0) + 1
        return sorted(counts.items(), key=lambda x: -x[1])

    # ── Interview Scores ──────────────────────────────────────────────────────

    def save_interview_score(self, session_id: str, topic: Optional[str],
                             score: int, mode: str, weaknesses: list,
                             strengths: list, summary: str):
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO interview_scores
                (session_id, topic, score, mode, weaknesses, strengths, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_id, topic, score, mode,
                  json.dumps(weaknesses), json.dumps(strengths), summary))

    def get_avg_score_by_topic(self) -> dict[str, float]:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT topic, AVG(score) as avg_score
                FROM interview_scores WHERE topic IS NOT NULL GROUP BY topic
            """).fetchall()
            return {r["topic"]: round(r["avg_score"], 2) for r in rows}

    # ── Full Dashboard ────────────────────────────────────────────────────────

    def get_full_summary(self) -> dict:
        patterns = self.get_pattern_summary()
        difficulty = self.get_difficulty_summary()
        problems = self.get_all_problems()
        recent = self.get_recently_solved(7)
        mastery = self.get_mastery_summary()
        session_weaknesses = self.get_aggregated_weaknesses_from_sessions()
        kb_weaknesses = self.get_all_weaknesses()
        scores = self.get_avg_score_by_topic()
        roadmap = self.get_roadmap_items()

        missing_patterns = [p for p in DSA_PATTERNS if p not in patterns]

        return {
            "total_problems": len(problems),
            "patterns_covered": patterns,
            "missing_patterns": missing_patterns,
            "difficulty_breakdown": difficulty,
            "recently_solved": [p["problem_name"] for p in recent],
            "mastery_by_topic": mastery,
            "session_weaknesses": session_weaknesses[:5],
            "kb_weaknesses": [w["weakness"] for w in kb_weaknesses[:5]],
            "avg_scores_by_topic": scores,
            "roadmap_items": [r["item"] for r in roadmap[:5]],
        }
