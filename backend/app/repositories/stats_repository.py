import json
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional
from collections import defaultdict

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class StatsRepository:
    def __init__(self):
        self.base_dir = Path(settings.DATA_DIR) / "stats"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.weakness_file = self.base_dir / "weaknesses.json"
        self.star_file = self.base_dir / "star_scores.json"
        self.activity_file = self.base_dir / "activity.json"

    def _load(self, path: Path) -> list:
        if not path.exists():
            return []
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, path: Path, data: list) -> None:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # --- Weakness ---

    def save_weakness_report(self, session_id: str, topic: Optional[str], report: dict) -> None:
        records = self._load(self.weakness_file)
        records.append({
            "session_id": session_id,
            "topic": topic,
            "report": report,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._save(self.weakness_file, records)

    def get_weakness_history(self, limit: int = 20) -> list:
        return self._load(self.weakness_file)[-limit:]

    def get_aggregated_weaknesses(self) -> dict:
        records = self._load(self.weakness_file)
        weakness_count: dict[str, int] = defaultdict(int)
        strength_count: dict[str, int] = defaultdict(int)
        scores = []
        topic_scores: dict[str, list] = defaultdict(list)

        for r in records:
            report = r.get("report", {})
            for w in report.get("weaknesses", []):
                weakness_count[w] += 1
            for s in report.get("strengths", []):
                strength_count[s] += 1
            if score := report.get("score"):
                scores.append(score)
            for t, ts in report.get("topic_scores", {}).items():
                topic_scores[t].append(ts)

        return {
            "top_weaknesses": sorted(weakness_count.items(), key=lambda x: -x[1])[:10],
            "top_strengths": sorted(strength_count.items(), key=lambda x: -x[1])[:5],
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "avg_topic_scores": {t: round(sum(v) / len(v), 2) for t, v in topic_scores.items()},
            "total_sessions_analyzed": len(records),
        }

    # --- STAR ---

    def save_star_score(self, question: str, answer: str, score: dict) -> None:
        records = self._load(self.star_file)
        records.append({
            "question": question,
            "answer": answer[:500],
            "score": score,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._save(self.star_file, records)

    def get_star_history(self, limit: int = 20) -> list:
        return self._load(self.star_file)[-limit:]

    def get_star_stats(self) -> dict:
        records = self._load(self.star_file)
        if not records:
            return {"avg_score": 0, "total": 0, "score_distribution": {}, "recent": []}
        scores = [r["score"].get("score", 0) for r in records]
        dist: dict[int, int] = defaultdict(int)
        for s in scores:
            dist[s] += 1
        return {
            "avg_score": round(sum(scores) / len(scores), 2),
            "total": len(records),
            "score_distribution": dict(dist),
            "recent": records[-5:],
        }

    # --- Activity / streak ---

    def record_activity(self, topic: Optional[str]) -> None:
        records = self._load(self.activity_file)
        records.append({
            "date": date.today().isoformat(),
            "topic": topic or "general",
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._save(self.activity_file, records)

    def get_dashboard(self) -> dict:
        records = self._load(self.activity_file)
        topic_counts: dict[str, int] = defaultdict(int)
        daily: dict[str, int] = defaultdict(int)

        for r in records:
            topic_counts[r.get("topic", "general")] += 1
            daily[r.get("date", "")] += 1

        # Streak
        streak = 0
        today = date.today()
        for i in range(365):
            d = (today - timedelta(days=i)).isoformat()
            if d in daily:
                streak += 1
            else:
                break

        weakness_summary = self.get_aggregated_weaknesses()
        star_stats = self.get_star_stats()

        return {
            "total_sessions": len(records),
            "streak_days": streak,
            "topic_breakdown": dict(topic_counts),
            "daily_activity": dict(sorted(daily.items())[-14:]),
            "avg_score": weakness_summary["avg_score"],
            "top_weaknesses": weakness_summary["top_weaknesses"][:5],
            "star_avg": star_stats["avg_score"],
            "star_total": star_stats["total"],
        }
