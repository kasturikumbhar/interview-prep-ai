import json
import re
import uuid
from typing import Optional
from app.services.llm_service import LLMService
from app.repositories.interview_repository import (
    InterviewRepository, ResumeRepository, StoryRepository
)
from app.core.logging import get_logger

logger = get_logger(__name__)
llm = LLMService()
interview_repo = InterviewRepository()
resume_repo = ResumeRepository()
story_repo = StoryRepository()

QUESTION_PROMPTS = {
    "dsa": """You are a DSA interviewer at a top tech company. The candidate has {exp} years experience.
Resume context: {resume}
Difficulty: {difficulty}

Ask ONE {difficulty} DSA problem. State it clearly with constraints and examples.
Do not give hints or solutions. Just the problem statement.""",

    "system_design": """You are a Principal Engineer interviewing a {exp}-year senior engineer.
Resume context: {resume}
Difficulty: {difficulty}

Ask ONE system design question appropriate for {difficulty} difficulty.
State requirements clearly. Do not guide the answer.""",

    "java": """You are a Java backend interviewer. Candidate has {exp} years experience.
Resume context: {resume}
Difficulty: {difficulty}

Ask ONE {difficulty} Java/Spring question. Could be conceptual or code-based.
Focus on practical production scenarios.""",

    "python": """You are a Python/data engineering interviewer. Candidate has {exp} years experience.
Resume context: {resume}
Difficulty: {difficulty}

Ask ONE {difficulty} Python or PySpark question. Focus on practical data engineering.""",

    "aws": """You are an AWS Solutions Architect interviewer. Candidate has {exp} years experience.
Resume context: {resume}
Difficulty: {difficulty}

Ask ONE {difficulty} AWS architecture question. Focus on real design decisions.""",

    "behavioral": """You are a senior engineering manager conducting behavioral interviews.
Resume context: {resume}
Relevant stories the candidate has: {stories}

Ask ONE STAR-format behavioral question. Be specific. Do not suggest structure.""",
}

FOLLOW_UP_PROMPT = """You are a technical interviewer. Previous exchange:

Question: {question}
Candidate answer: {answer}

Evaluate this answer:
1. Score it 1-10
2. Give specific feedback (2-3 sentences)
3. Ask ONE follow-up question that probes deeper or exposes a gap

Return ONLY valid JSON:
{{
  "score": 7,
  "feedback": "specific feedback here",
  "follow_up_question": "follow-up question here",
  "answer_quality": "good|partial|weak"
}}"""

RESUME_EXTRACT_PROMPT = """Extract structured information from this resume text.
Return ONLY valid JSON:
{{
  "skills": ["skill1", "skill2"],
  "technologies": ["tech1", "tech2"],
  "projects": ["Project A: brief description", "Project B: brief description"],
  "achievements": ["Achievement 1", "Achievement 2"]
}}

Resume text:
{text}"""

FINAL_REPORT_PROMPT = """You are evaluating a complete technical interview session.

Topic: {topic}
Difficulty: {difficulty}

Questions and answers:
{qa_text}

Generate a comprehensive final report. Return ONLY valid JSON:
{{
  "communication": 7,
  "technical_depth": 6,
  "tradeoff_reasoning": 5,
  "problem_solving": 7,
  "overall": 6,
  "strengths": ["specific strength 1", "specific strength 2"],
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "improvement_actions": ["concrete action 1", "concrete action 2", "concrete action 3"]
}}

All scores are 0-10. Be honest and specific."""


async def _llm_json(prompt: str) -> Optional[dict]:
    try:
        response = await llm.chat([{"role": "user", "content": prompt}], mode="chat")
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        start = next((i for i, c in enumerate(clean) if c in "{["), 0)
        return json.loads(clean[start:])
    except Exception as e:
        logger.error(f"LLM JSON failed: {e}")
        return None


async def start_interview(topic: str, difficulty: str) -> dict:
    session_id = str(uuid.uuid4())
    resume_ctx = resume_repo.get_context_string()

    # For behavioral, include story bank context
    stories_ctx = ""
    if topic == "behavioral":
        stories = story_repo.get_all()
        if stories:
            stories_ctx = "\n".join(f"- {s['title']}: {s['situation'][:100]}" for s in stories[:5])

    prompt_template = QUESTION_PROMPTS.get(topic, QUESTION_PROMPTS["dsa"])
    prompt = prompt_template.format(
        exp=6,
        resume=resume_ctx or "No resume uploaded",
        difficulty=difficulty,
        stories=stories_ctx or "No stories stored yet",
    )

    question_text = await llm.chat([{"role": "user", "content": prompt}], mode=topic)

    interview_repo.create_session(session_id, topic, difficulty, resume_ctx)
    q_id = interview_repo.add_question(session_id, question_text, 1)

    return {
        "session_id": session_id,
        "topic": topic,
        "difficulty": difficulty,
        "question_id": q_id,
        "question": question_text,
        "question_number": 1,
    }


async def answer_question(session_id: str, answer_text: str) -> dict:
    session = interview_repo.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if session["status"] == "ended":
        raise ValueError("Interview already ended")

    latest_q = interview_repo.get_latest_question(session_id)
    if not latest_q:
        raise ValueError("No question found for this session")

    # Evaluate answer and generate follow-up
    eval_prompt = FOLLOW_UP_PROMPT.format(
        question=latest_q["question_text"],
        answer=answer_text,
    )
    eval_result = await _llm_json(eval_prompt)
    if not eval_result:
        eval_result = {"score": 5, "feedback": "Could not evaluate", "follow_up_question": "", "answer_quality": "unknown"}

    score = eval_result.get("score", 5)
    feedback = eval_result.get("feedback", "")
    follow_up = eval_result.get("follow_up_question", "")

    # Save answer
    interview_repo.add_answer(
        session_id, latest_q["id"], answer_text, score, feedback, follow_up
    )

    # Store follow-up as next question if exists
    next_q_id = None
    next_question = None
    question_count = interview_repo.get_question_count(session_id)

    if follow_up and question_count < 10:
        next_q_id = interview_repo.add_question(session_id, follow_up, question_count + 1)
        next_question = follow_up

    return {
        "session_id": session_id,
        "score": score,
        "feedback": feedback,
        "answer_quality": eval_result.get("answer_quality", "unknown"),
        "next_question_id": next_q_id,
        "next_question": next_question,
        "question_number": question_count + 1 if next_question else None,
        "session_complete": not bool(next_question),
    }


async def generate_report(session_id: str) -> dict:
    session = interview_repo.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Return cached report if exists
    cached = interview_repo.get_report(session_id)
    if cached:
        return cached

    qa_pairs = interview_repo.get_session_qa(session_id)
    if not qa_pairs:
        raise ValueError("No Q&A data found")

    qa_text = ""
    for qa in qa_pairs:
        qa_text += f"\nQ{qa['question_number']}: {qa['question_text']}\n"
        if qa.get("answer_text"):
            qa_text += f"A: {qa['answer_text']}\n"
            qa_text += f"Score: {qa.get('score', '?')}/10 | {qa.get('feedback', '')}\n"

    prompt = FINAL_REPORT_PROMPT.format(
        topic=session["topic"],
        difficulty=session["difficulty"],
        qa_text=qa_text[:5000],
    )

    report = await _llm_json(prompt)
    if not report:
        report = {
            "communication": 0, "technical_depth": 0, "tradeoff_reasoning": 0,
            "problem_solving": 0, "overall": 0,
            "strengths": [], "weaknesses": [], "improvement_actions": ["Could not generate report"]
        }

    report["session_id"] = session_id
    report["topic"] = session["topic"]
    report["difficulty"] = session["difficulty"]
    report["question_count"] = len(qa_pairs)
    report["qa_summary"] = [
        {"q": qa["question_text"][:100], "score": qa.get("score")} for qa in qa_pairs
    ]

    interview_repo.end_session(session_id, report)
    return report


async def extract_resume(text: str) -> dict:
    prompt = RESUME_EXTRACT_PROMPT.format(text=text[:4000])
    result = await _llm_json(prompt)
    if not result:
        result = {"skills": [], "technologies": [], "projects": [], "achievements": []}
    resume_repo.save(
        raw_text=text,
        skills=result.get("skills", []),
        projects=result.get("projects", []),
        technologies=result.get("technologies", []),
        achievements=result.get("achievements", []),
    )
    return result
