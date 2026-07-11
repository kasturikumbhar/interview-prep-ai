"""
Analysis service — revision questions use LLM knowledge + KB context.
Not restricted to only what's in KB text. Generates real interview questions
based on topics the candidate has touched, using LLM's full knowledge.
"""
import json
import re
from typing import Optional
from app.services.llm_service import LLMService
from app.core.logging import get_logger

logger = get_logger(__name__)
llm = LLMService()

WEAKNESS_PROMPT = """Analyze this software engineering interview conversation for a 6-year senior engineer.

Conversation:
{conversation}

Return ONLY valid JSON:
{{
  "weaknesses": ["specific weakness with evidence"],
  "strengths": ["specific strength with evidence"],
  "score": 3,
  "topic_scores": {{"dsa": 3, "communication": 4}},
  "summary": "One sentence honest assessment"
}}"""

STAR_PROMPT = """You are a senior engineering manager evaluating a STAR behavioral answer for a senior engineer role.

Question: {question}
Answer: {answer}

Return ONLY valid JSON:
{{
  "score": 4,
  "situation_score": 4,
  "task_score": 3,
  "action_score": 5,
  "result_score": 4,
  "missing": ["specific gap"],
  "strengths": ["specific strength"],
  "improved_answer_hint": "One concrete sentence on what would make this 5/5",
  "verdict": "Honest one-line verdict"
}}"""


# Topic-specific question generation prompts
# Uses LLM knowledge + KB context as hints about what the candidate has covered
REVISION_PROMPT = """You are a senior interviewer at a top tech company (Google/Amazon/Uber level).

The candidate is a 6-year experienced engineer. They have studied these topics (use as context for relevance, not as source text to copy):
{content}

Generate exactly {count} real interview questions for topic: {topic_label}

CRITICAL RULES:
1. Every entry MUST be a complete grammatical question ending with "?"
2. Questions must test DEEP understanding — not definitions
3. Questions must be the kind actually asked in senior engineer interviews
4. Use your own knowledge of {topic_label} — do not just copy text from the context
5. REJECT anything that is: a topic name, an incomplete phrase, metadata, or notes

GOOD examples for DSA:
- "You have an array of n integers and need to find all pairs that sum to a target. What is the optimal approach and why does a hash set work here while sorting + two pointers doesn't for this exact variant?"
- "Given a binary tree, how would you detect if it is a valid BST, and what edge case breaks the naive approach of just checking left < root < right at each node?"

GOOD examples for Java:
- "Your @Transactional service method calls another @Transactional method in the same class. Does Spring create a new transaction? Why does self-invocation break AOP proxying?"
- "You have a HashMap that's being read by 100 threads and written by 1 thread. Why is HashMap not safe here even for reads, and what are your options?"

GOOD examples for AWS:
- "Your Lambda function is processing SQS messages and occasionally hitting the 15-minute timeout. What are your architectural options and what are the trade-offs of each?"
- "You need to migrate a 5TB RDS MySQL database to Aurora PostgreSQL with under 10 minutes of downtime. Walk through your strategy."

GOOD examples for System Design:
- "Design a distributed rate limiter that works across 50 servers handling 1M req/s. How do you handle the race condition in a distributed counter?"

GOOD examples for Behavioral:
- "Tell me about a time you pushed back on a technical decision from your tech lead and how you handled the disagreement professionally?"

BAD (never generate these):
- "Two Pointers" (just a topic name)
- "Eventually learned global decomposition" (fragment from notes)
- "Space optimization using" (incomplete phrase)
- "ask about binary search" (instruction not a question)
- "The candidate struggled with" (metadata)

Return ONLY a valid JSON array:
[
  {{
    "question": "Complete interview question ending with ?",
    "topic": "{topic}",
    "difficulty": "medium",
    "hint": "Key insight or invariant needed: be specific, 1-2 sentences",
    "expected_answer_points": [
      "specific point 1 — what a good answer must include",
      "specific point 2",
      "specific point 3"
    ]
  }}
]"""


DUE_TODAY_QUESTIONS_PROMPT = """You are a senior interviewer. Generate ONE real interview question for this topic.

Topic area: {topic}
Subtopic: {subtopic}

Generate a single interview question that tests understanding of "{subtopic}" in the context of {topic}.

Rules:
- Must be a complete question ending with "?"
- Must be the kind asked in senior engineer interviews
- Use your full knowledge of the subject — not restricted to any notes
- Include a specific hint and 2-3 answer points

Return ONLY valid JSON (single object, not array):
{{
  "question": "Complete interview question ending with ?",
  "topic": "{topic}",
  "difficulty": "medium",
  "hint": "Key insight needed to answer this",
  "expected_answer_points": ["point 1", "point 2", "point 3"]
}}"""


TOPIC_LABELS = {
    "dsa": "Data Structures & Algorithms",
    "system_design": "System Design",
    "java": "Java Backend Engineering",
    "python": "Python and PySpark",
    "aws": "AWS Cloud Architecture",
    "behavioral": "Behavioral / Leadership",
    "general": "Software Engineering",
    "projects": "Software Projects",
}


def _is_garbage(q: dict) -> bool:
    """Reject malformed questions."""
    text = q.get("question", "").strip()
    if not text or len(text) < 25:
        return True
    if not text.endswith("?"):
        return True
    lower = text.lower()
    garbage_starts = [
        "ask", "avoid", "the user", "the candidate", "note:", "remember",
        "question:", "hint:", "topic:", "difficulty:", "based on",
        "eventually", "space optimization", "into", "using", "learned",
        "understood", "1d dp", "2d dp",  # bare topic names
    ]
    if any(lower.startswith(g) for g in garbage_starts):
        return True
    # Too short to be a real question
    if len(text.split()) < 8:
        return True
    return False


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


async def generate_revision_questions(content: str, count: int = 5, topic: str = "dsa") -> list[dict]:
    """
    Generate real interview questions using LLM knowledge.
    KB content is used as context about what topics the candidate has studied,
    not as the source text to copy from.
    """
    topic_label = TOPIC_LABELS.get(topic, topic.replace("_", " ").title())

    # Summarize KB content into topic hints (don't dump raw text)
    content_summary = content[:2000] if content else f"General {topic_label} topics"

    prompt = REVISION_PROMPT.format(
        content=content_summary,
        count=count,
        topic=topic,
        topic_label=topic_label,
    )

    result = await _call_llm_json(prompt)
    if not result or not isinstance(result, list):
        logger.warning(f"Non-list result for topic={topic}")
        return []

    # Filter garbage
    clean = [q for q in result if not _is_garbage(q)]

    # Ensure all fields populated
    for q in clean:
        if not q.get("hint"):
            q["hint"] = "Think about the core mechanism and edge cases."
        if not q.get("expected_answer_points"):
            q["expected_answer_points"] = []
        if not q.get("difficulty"):
            q["difficulty"] = "medium"
        q["topic"] = topic

    logger.info(f"Generated {len(clean)}/{count} valid questions for topic={topic}")
    return clean


async def generate_question_for_subtopic(topic: str, subtopic: str) -> Optional[dict]:
    """
    Generate a single proper interview question for a subtopic from the due-today list.
    Used to convert raw KB mastery entries into real interview questions.
    """
    # Clean up subtopic — remove garbage like "Eventually learned X"
    clean_subtopic = subtopic
    garbage_prefixes = [
        "eventually learned", "eventually understood", "space optimization using",
        "known weakness:", "mastery level:", "review and strengthen",
    ]
    for prefix in garbage_prefixes:
        if clean_subtopic.lower().startswith(prefix):
            # Extract the actual topic from after the prefix
            clean_subtopic = clean_subtopic[len(prefix):].strip().strip(":").strip()
            break

    if not clean_subtopic or len(clean_subtopic) < 3:
        return None

    prompt = DUE_TODAY_QUESTIONS_PROMPT.format(
        topic=TOPIC_LABELS.get(topic, topic),
        subtopic=clean_subtopic,
    )

    result = await _call_llm_json(prompt)
    if not result or not isinstance(result, dict):
        return None

    # Validate
    if _is_garbage(result):
        return None

    result["topic"] = topic
    result["subtopic"] = clean_subtopic
    if not result.get("hint"):
        result["hint"] = "Think about the core mechanism and common gotchas."
    if not result.get("expected_answer_points"):
        result["expected_answer_points"] = []

    return result


async def detect_dsa_patterns(files_content: dict) -> dict:
    combined = ""
    for filename, content in list(files_content.items())[:10]:
        combined += f"\n\n=== {filename} ===\n{content[:500]}"

    prompt = f"""Analyze these DSA solution files. Return ONLY valid JSON:
{{
  "patterns_found": ["pattern name"],
  "patterns_missing": ["pattern name"],
  "problem_count": 12,
  "complexity_issues": ["specific issue"],
  "recommendations": ["specific recommendation"]
}}

Files:
{combined[:4000]}"""

    result = await _call_llm_json(prompt)
    if not result or not isinstance(result, dict):
        return {"patterns_found": [], "patterns_missing": [], "problem_count": 0, "complexity_issues": [], "recommendations": []}
    return result
