"""
Progress Service — multi-topic progress intelligence.
Answers progress questions from structured SQLite data, never from LLM inference.
"""
import re
import json
from typing import Optional
from app.repositories.progress_repository import ProgressRepository, DSA_PATTERNS
from app.services.llm_service import LLMService
from app.core.logging import get_logger

logger = get_logger(__name__)
repo = ProgressRepository()
llm = LLMService()


def get_dsa_progress() -> dict:
    return repo.get_full_summary()


def get_pattern_gaps() -> dict:
    covered = repo.get_pattern_summary()
    missing = [p for p in DSA_PATTERNS if p not in covered]
    weak = {p: c for p, c in covered.items() if c < 2}
    return {
        "covered_patterns": covered,
        "missing_patterns": missing,
        "weak_patterns": weak,
        "coverage_percent": round(
            len([p for p in DSA_PATTERNS if p in covered]) / len(DSA_PATTERNS) * 100, 1
        ),
    }


def get_all_topic_mastery() -> dict:
    """Returns mastery across ALL topics from KB files."""
    return repo.get_mastery_summary()


def get_revision_candidates() -> list[dict]:
    problems = repo.get_all_problems()
    candidates = []
    for p in problems:
        score = 0
        if p.get("revision_count", 0) == 0:
            score += 3
        elif p.get("revision_count", 0) == 1:
            score += 1
        if p.get("difficulty") == "Hard":
            score += 2
        elif p.get("difficulty") == "Medium":
            score += 1
        if not p.get("last_revised"):
            score += 2
        candidates.append({**p, "priority_score": score})
    candidates.sort(key=lambda x: -x["priority_score"])
    return candidates[:10]


def get_what_to_study_today() -> dict:
    """Structured recommendations from real data — no LLM guessing."""
    gaps = get_pattern_gaps()
    revision = get_revision_candidates()
    mastery = get_all_topic_mastery()
    kb_weaknesses = repo.get_all_weaknesses()
    session_weaknesses = repo.get_aggregated_weaknesses_from_sessions()
    roadmap = repo.get_roadmap_items()

    recommendations = []

    # 1. Missing DSA patterns
    if gaps["missing_patterns"]:
        top = gaps["missing_patterns"][:2]
        recommendations.append({
            "priority": 1,
            "type": "new_pattern",
            "topic": "dsa",
            "action": f"Learn {', '.join(top)} — not yet in your solutions",
            "reason": "Pattern gap in DSA coverage",
        })

    # 2. Weak topics from KB mastery data
    for cat, data in mastery.items():
        if data.get("weak_topics"):
            weak = data["weak_topics"][:1]
            recommendations.append({
                "priority": 2,
                "type": "strengthen_topic",
                "topic": cat,
                "action": f"Strengthen {cat.upper()}: {', '.join(weak)}",
                "reason": f"Marked as weak/introduced in your notes",
            })

    # 3. Revision queue
    if revision:
        top = revision[0]
        recommendations.append({
            "priority": 3,
            "type": "revision",
            "topic": "dsa",
            "action": f"Revise '{top['problem_name']}' ({top.get('pattern', '?')})",
            "reason": f"Revised {top.get('revision_count', 0)}× | {top.get('difficulty', '?')}",
        })

    # 4. From KB roadmap
    if roadmap:
        recommendations.append({
            "priority": 4,
            "type": "roadmap",
            "topic": roadmap[0].get("category", "general"),
            "action": roadmap[0]["item"],
            "reason": "From your learning roadmap",
        })

    # 5. From session analysis
    if session_weaknesses:
        recommendations.append({
            "priority": 5,
            "type": "session_weakness",
            "topic": "general",
            "action": f"Work on: {session_weaknesses[0][0]}",
            "reason": f"Flagged {session_weaknesses[0][1]}× in session analysis",
        })

    return {
        "recommendations": recommendations[:5],
        "pattern_coverage": f"{gaps['coverage_percent']}%",
        "missing_dsa_count": len(gaps["missing_patterns"]),
        "revision_queue_size": len(revision),
        "top_kb_weakness": kb_weaknesses[0]["weakness"] if kb_weaknesses else None,
        "top_session_weakness": session_weaknesses[0][0] if session_weaknesses else None,
    }


async def generate_study_plan(days: int = 7) -> dict:
    summary = get_dsa_progress()
    mastery = get_all_topic_mastery()
    kb_weaknesses = [w["weakness"] for w in repo.get_all_weaknesses()[:5]]

    mastery_brief = {
        cat: {
            "avg": data["avg_mastery"],
            "weak": data["weak_topics"][:3],
            "strong": data["strong_topics"][:3],
        }
        for cat, data in mastery.items()
    }

    prompt = f"""You are a strict interview coach for a 6-year senior engineer targeting Google/Amazon/Uber.

Structured progress data (do NOT invent or modify):
- DSA problems solved: {summary['total_problems']}
- DSA patterns covered: {summary['patterns_covered']}
- DSA patterns missing: {summary['missing_patterns']}
- Difficulty breakdown: {summary['difficulty_breakdown']}
- Topic mastery across all areas: {mastery_brief}
- Known weaknesses: {kb_weaknesses}

Generate a concrete {days}-day study plan grounded in this data.
Name exact patterns, topics, and problem types.
Return ONLY valid JSON:
{{
  "days": [
    {{"day": 1, "focus": "pattern/topic", "tasks": ["task 1", "task 2"], "goal": "measurable outcome"}}
  ],
  "weekly_goal": "one sentence"
}}"""

    try:
        response = await llm.chat([{"role": "user", "content": prompt}], mode="chat")
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        start = next((i for i, c in enumerate(clean) if c in "{["), 0)
        return json.loads(clean[start:])
    except Exception as e:
        logger.error(f"Study plan failed: {e}")
        return {"error": "Could not generate plan", "data": summary}


def is_progress_question(message: str) -> bool:
    keywords = [
        "what have i solved", "what did i solve", "problems solved",
        "patterns covered", "patterns i know", "what patterns",
        "weak areas", "weak at", "weaknesses", "struggling with",
        "what should i study", "what to study", "study today",
        "what to revise", "revise next", "revision",
        "my progress", "how am i doing",
        "topics covered", "what topics", "which topics",
        "missing patterns", "pattern gaps", "haven't covered",
        "recently solved", "solved recently",
        "mastery", "what do i know", "where am i",
        "java topics", "aws topics", "python topics", "system design topics",
        "behavioral topics", "what have i learned",
    ]
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in keywords)


def build_progress_context(message: str) -> str:
    """Build structured context from DB for injection into LLM prompt."""
    msg_lower = message.lower()
    sections = []

    # DSA-specific
    if any(k in msg_lower for k in ["pattern", "dsa", "leetcode", "problem", "algorithm"]):
        summary = repo.get_full_summary()
        sections.append(f"DSA Problems solved: {summary['total_problems']}")
        sections.append(f"DSA Patterns covered: {summary['patterns_covered']}")
        sections.append(f"DSA Patterns missing: {summary['missing_patterns']}")
        sections.append(f"Difficulty breakdown: {summary['difficulty_breakdown']}")
        if summary.get("recently_solved"):
            sections.append(f"Recently solved: {summary['recently_solved'][:5]}")

    # All-topic mastery (from KB files)
    if any(k in msg_lower for k in ["topic", "covered", "learned", "know", "mastery", "progress"]):
        mastery = get_all_topic_mastery()
        for cat, data in mastery.items():
            sections.append(
                f"{cat.upper()} mastery: {data['topic_count']} topics, avg {data['avg_mastery']}/5 | "
                f"Strong: {data['strong_topics'][:3]} | Weak: {data['weak_topics'][:3]}"
            )

    # Weaknesses
    if any(k in msg_lower for k in ["weak", "struggle", "bad at", "improve", "gap"]):
        kb_w = [w["weakness"] for w in repo.get_all_weaknesses()[:5]]
        session_w = repo.get_aggregated_weaknesses_from_sessions()
        if kb_w:
            sections.append(f"Weaknesses from your notes: {kb_w}")
        if session_w:
            sections.append(f"Weaknesses from sessions: {[w[0] for w in session_w[:3]]}")

    # Study recommendations
    if any(k in msg_lower for k in ["study", "revise", "today", "next", "recommend", "should i"]):
        plan = get_what_to_study_today()
        actions = [r["action"] for r in plan["recommendations"]]
        sections.append(f"Study recommendations: {actions}")
        sections.append(f"Pattern coverage: {plan['pattern_coverage']}")

    if not sections:
        # Fallback: give a broad summary
        summary = repo.get_full_summary()
        mastery = get_all_topic_mastery()
        sections.append(f"DSA: {summary['total_problems']} problems solved, patterns: {list(summary['patterns_covered'].keys())[:5]}")
        for cat, data in mastery.items():
            sections.append(f"{cat.upper()}: {data['topic_count']} topics tracked, avg {data['avg_mastery']}/5")

    return (
        "--- Structured progress data (from your actual records, not inferred) ---\n"
        + "\n".join(sections)
        + "\n--- End progress data ---"
    )
