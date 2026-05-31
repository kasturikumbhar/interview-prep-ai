"""
Session Summary Service — generates structured summaries every N messages.
Summaries become long-term memory injected into future prompts.
"""
import json
import re
from typing import Optional
from app.services.llm_service import LLMService
from app.repositories.progress_repository import ProgressRepository
from app.core.logging import get_logger

logger = get_logger(__name__)
llm = LLMService()
repo = ProgressRepository()

SUMMARY_EVERY_N = 6  # summarize after every 6 messages

SUMMARY_PROMPT = """You are analyzing an interview coaching conversation to extract structured progress data.

Conversation:
{conversation}

Extract structured data. Return ONLY valid JSON, nothing else:
{{
  "topics_covered": ["specific topics discussed, e.g. 'Binary Search on rotated array'"],
  "strengths": ["specific things the candidate did well"],
  "weaknesses": ["specific gaps or mistakes made"],
  "next_actions": ["concrete next steps, e.g. 'Practice Two Heaps pattern - only 1 solution'"],
  "problems_mentioned": [
    {{"name": "problem name", "pattern": "pattern", "difficulty": "Easy/Medium/Hard", "status": "solved/struggled"}}
  ]
}}

Be specific. Do not invent information not present in the conversation.
If nothing fits a category, use an empty array."""


async def maybe_summarize(session_id: str, messages: list, topic: Optional[str]) -> Optional[dict]:
    """
    Called after each assistant response.
    Summarizes if message count crosses a threshold.
    Returns summary dict if generated, None otherwise.
    """
    # Only summarize at multiples of N
    if len(messages) < SUMMARY_EVERY_N or len(messages) % SUMMARY_EVERY_N != 0:
        return None

    # Take the last N messages for summarization
    recent = messages[-SUMMARY_EVERY_N:]
    conversation_text = "\n".join(
        f"{m.role.upper()}: {m.content[:500]}"
        for m in recent
        if m.role in ("user", "assistant")
    )

    try:
        response = await llm.chat(
            [{"role": "user", "content": SUMMARY_PROMPT.format(conversation=conversation_text)}],
            mode="chat",
        )
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        start = next((i for i, c in enumerate(clean) if c in "{["), 0)
        summary = json.loads(clean[start:])

        # Persist summary
        repo.save_session_summary(session_id, topic, summary, len(messages))

        # Extract and persist any problems mentioned
        for p in summary.get("problems_mentioned", []):
            if p.get("name"):
                repo.upsert_problem(
                    problem_name=p["name"],
                    pattern=p.get("pattern"),
                    difficulty=p.get("difficulty"),
                    status="solved" if p.get("status") == "solved" else "attempted",
                )

        logger.info(f"Session {session_id}: summary generated at {len(messages)} messages")
        return summary

    except Exception as e:
        logger.warning(f"Could not summarize session {session_id}: {e}")
        return None


def get_long_term_memory_context() -> str:
    """
    Build context string from recent session summaries.
    Injected into every prompt so the model knows your history.
    """
    summaries = repo.get_recent_summaries(limit=3)
    if not summaries:
        return ""

    lines = ["--- Your recent session history (long-term memory) ---"]
    for s in summaries:
        lines.append(f"\nSession ({s.get('created_at', '')[:10]}) | Topic: {s.get('topic', 'general')}")
        if s.get("topics_covered"):
            lines.append(f"  Covered: {', '.join(s['topics_covered'])}")
        if s.get("weaknesses"):
            lines.append(f"  Weaknesses: {', '.join(s['weaknesses'])}")
        if s.get("next_actions"):
            lines.append(f"  Action items: {', '.join(s['next_actions'])}")
    lines.append("--- End session history ---")
    return "\n".join(lines)
