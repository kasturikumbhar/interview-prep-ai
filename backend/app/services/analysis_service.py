"""
Analysis service — STAR scoring, weakness analysis, senior-level revision questions.
Revision questions are grounded in KB content and must be interview-level.
"""
import json
import re
from typing import Optional
from app.services.llm_service import LLMService
from app.core.logging import get_logger

logger = get_logger(__name__)
llm = LLMService()

WEAKNESS_PROMPT = """You are analyzing a software engineering interview conversation for a 6-year senior engineer.

Conversation:
{conversation}

Be specific and direct. Return ONLY valid JSON, nothing else:
{{
  "weaknesses": ["specific weakness with context, e.g. 'Struggled to derive time complexity for heap-based merge'"],
  "strengths": ["specific strength with evidence"],
  "score": 3,
  "topic_scores": {{"dsa": 3, "communication": 4}},
  "summary": "One sentence honest assessment"
}}

Score 1-5. Include only topics that appeared."""

STAR_PROMPT = """You are a senior engineering manager evaluating a STAR behavioral answer for a senior engineer role.

Question: {question}
Answer: {answer}

Be strict. Junior-level answers score 2-3 even if structurally correct.
Return ONLY valid JSON:
{{
  "score": 4,
  "situation_score": 4,
  "task_score": 3,
  "action_score": 5,
  "result_score": 4,
  "missing": ["specific gap, e.g. 'No mention of team size or stakeholders'"],
  "strengths": ["specific strength, e.g. 'Quantified impact: 40% latency reduction'"],
  "improved_answer_hint": "One concrete sentence on what would make this 5/5",
  "verdict": "Honest one-line verdict"
}}"""

REVISION_QUESTIONS_PROMPT = """You are a senior interviewer at Google/Amazon creating revision questions for a 6-year experienced engineer.

Knowledge base content covering these topics:
{content}

Generate exactly {count} interview-level revision questions.

RULES:
- Questions must test DEEP understanding, not surface recall
- BAD: "What is binary search?" GOOD: "You have a sorted rotated array and need to find a target. Walk me through the invariant you maintain and why it holds after each iteration."
- BAD: "What is a heap?" GOOD: "You need the median of a data stream after each insertion. What two-heap structure achieves O(log n) insert and O(1) median? What invariant do you maintain between the two heaps?"
- BAD: "What is SQS?" GOOD: "Your service consumes from SQS but occasionally processes the same message twice. What are the possible causes and how do you handle idempotency at the consumer?"
- Each question should require 3-5 sentences to answer correctly
- Questions must be directly derived from the content provided, not generic

Return ONLY a valid JSON array:
[
  {{
    "question": "full question text",
    "topic": "dsa|system_design|java|python|aws|behavioral",
    "difficulty": "medium|hard",
    "hint": "key concept or invariant needed to answer this",
    "expected_answer_points": ["point 1", "point 2", "point 3"]
  }}
]"""

PATTERN_PROMPT = """You are analyzing DSA solution files for a senior engineer.

Files:
{content}

Return ONLY valid JSON:
{{
  "patterns_found": ["pattern name"],
  "patterns_missing": ["pattern name"],
  "problem_count": 12,
  "complexity_issues": ["specific file and issue"],
  "recommendations": ["specific actionable recommendation"]
}}"""


async def _call_llm_json(prompt: str) -> Optional[dict]:
    try:
        response = await llm.chat(
            [{"role": "user", "content": prompt}],
            mode="chat",
        )
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        start = next((i for i, c in enumerate(clean) if c in "{["), 0)
        return json.loads(clean[start:])
    except Exception as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return None


async def analyze_weakness(conversation: list[dict]) -> dict:
    conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)
    result = await _call_llm_json(WEAKNESS_PROMPT.format(conversation=conv_text[:4000]))
    if not result or not isinstance(result, dict):
        return {"weaknesses": ["Analysis failed"], "strengths": [], "score": 0, "topic_scores": {}, "summary": "Could not analyze"}
    return result


async def score_star_answer(question: str, answer: str) -> dict:
    result = await _call_llm_json(STAR_PROMPT.format(question=question[:500], answer=answer[:2000]))
    if not result or not isinstance(result, dict):
        return {"score": 0, "verdict": "Scoring failed", "missing": [], "strengths": [], "improved_answer_hint": ""}
    return result


async def generate_revision_questions(content: str, count: int = 5) -> list[dict]:
    prompt = REVISION_QUESTIONS_PROMPT.format(content=content[:4000], count=count)
    result = await _call_llm_json(prompt)
    if not result or not isinstance(result, list):
        return []
    return result


async def detect_dsa_patterns(files_content: dict) -> dict:
    combined = ""
    for filename, content in list(files_content.items())[:10]:
        combined += f"\n\n=== {filename} ===\n{content[:500]}"
    result = await _call_llm_json(PATTERN_PROMPT.format(content=combined[:4000]))
    if not result or not isinstance(result, dict):
        return {"patterns_found": [], "patterns_missing": [], "problem_count": 0, "complexity_issues": [], "recommendations": []}
    return result
