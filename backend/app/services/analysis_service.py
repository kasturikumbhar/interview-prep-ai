"""
Analysis service — weakness tracking, STAR scoring, revision question generation,
DSA pattern detection. All via local Ollama — no external APIs.
"""
import json
import re
from typing import Optional
from app.services.llm_service import LLMService
from app.core.logging import get_logger

logger = get_logger(__name__)
llm = LLMService()

WEAKNESS_PROMPT = """You are analyzing a software engineering interview conversation to identify weaknesses.

Conversation:
{conversation}

Identify weaknesses in the candidate's answers. Be specific and direct — no softening.
Return ONLY valid JSON in this exact format, nothing else:
{{
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "strengths": ["strength 1"],
  "score": 3,
  "topic_scores": {{"dsa": 3, "communication": 4}},
  "summary": "One sentence overall assessment"
}}

Score is 1-5. Include only topics that appeared in the conversation."""

STAR_PROMPT = """You are a senior engineering manager evaluating a STAR behavioral answer.

Question: {question}
Answer: {answer}

Score this answer strictly. Return ONLY valid JSON in this exact format, nothing else:
{{
  "score": 4,
  "situation_score": 4,
  "task_score": 3,
  "action_score": 5,
  "result_score": 4,
  "missing": ["specific result metrics", "team size context"],
  "strengths": ["clear situation setup", "concrete actions taken"],
  "improved_answer_hint": "One sentence on what would make this a 5/5 answer",
  "verdict": "Good answer but lacks quantifiable results"
}}

All scores are 1-5."""

REVISION_PROMPT = """You are a senior engineer creating targeted revision questions from study notes.

Notes:
{content}

Generate exactly {count} interview-relevant revision questions from these notes.
Return ONLY a valid JSON array, nothing else:
[
  {{
    "question": "What is the time complexity of merging K sorted lists using a heap?",
    "topic": "dsa",
    "difficulty": "medium",
    "hint": "Think about total elements and heap operations"
  }}
]

difficulty must be: easy, medium, or hard
topic must be one of: dsa, system_design, java, python, aws, behavioral"""

PATTERN_PROMPT = """You are analyzing DSA solutions to identify patterns and gaps.

Files:
{content}

Analyze these solutions and return ONLY valid JSON, nothing else:
{{
  "patterns_found": ["sliding window", "two pointers"],
  "patterns_missing": ["monotonic stack", "union find"],
  "problem_count": 12,
  "complexity_issues": ["solution.py uses O(n^2) where O(n log n) is possible"],
  "recommendations": ["Practice more DP problems", "Review graph traversal"]
}}"""


async def _call_llm_json(prompt: str) -> Optional[dict]:
    try:
        response = await llm.chat([{"role": "user", "content": prompt}], mode="chat")
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        start = next((i for i, c in enumerate(clean) if c in "{["), 0)
        return json.loads(clean[start:])
    except Exception as e:
        logger.error(f"LLM JSON parse failed: {e}\nResponse: {response[:200] if 'response' in dir() else 'no response'}")
        return None


async def analyze_weakness(conversation: list[dict]) -> dict:
    conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)
    result = await _call_llm_json(WEAKNESS_PROMPT.format(conversation=conv_text[:4000]))
    if not result or not isinstance(result, dict):
        return {"weaknesses": ["Analysis failed — try again"], "strengths": [], "score": 0, "topic_scores": {}, "summary": "Could not analyze"}
    return result


async def score_star_answer(question: str, answer: str) -> dict:
    result = await _call_llm_json(STAR_PROMPT.format(question=question[:500], answer=answer[:2000]))
    if not result or not isinstance(result, dict):
        return {"score": 0, "verdict": "Scoring failed — try again", "missing": [], "strengths": [], "improved_answer_hint": ""}
    return result


async def generate_revision_questions(content: str, count: int = 5) -> list[dict]:
    result = await _call_llm_json(REVISION_PROMPT.format(content=content[:3000], count=count))
    if not result or not isinstance(result, list):
        return []
    return result


async def detect_dsa_patterns(files_content: dict[str, str]) -> dict:
    combined = ""
    for filename, content in list(files_content.items())[:10]:
        combined += f"\n\n=== {filename} ===\n{content[:500]}"
    result = await _call_llm_json(PATTERN_PROMPT.format(content=combined[:4000]))
    if not result or not isinstance(result, dict):
        return {"patterns_found": [], "patterns_missing": [], "problem_count": 0, "complexity_issues": [], "recommendations": ["Analysis failed"]}
    return result
