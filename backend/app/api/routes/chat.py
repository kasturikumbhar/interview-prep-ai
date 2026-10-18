from fastapi import APIRouter, HTTPException
from app.models.chat import ChatRequest, ChatResponse, Message, Session
from app.services.llm_service import LLMService
from app.services.retrieval_service import build_context
from app.services.progress_service import is_progress_question, build_progress_context
from app.services.session_summary_service import maybe_summarize, get_long_term_memory_context
from app.repositories.session_repository import SessionRepository
from app.core.config import get_settings
from app.core.logging import get_logger

router   = APIRouter(prefix="/chat", tags=["chat"])
logger   = get_logger(__name__)
settings = get_settings()

LOW_CONFIDENCE_THRESHOLD = 0.35


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest):
    llm  = LLMService()
    repo = SessionRepository()

    session = repo.load(req.session_id) if req.session_id else None
    if not session:
        session = Session(topic=req.topic, mode=req.mode)

    history = [{"role": m.role, "content": m.content} for m in session.messages[-20:]]

    context_parts: list[str] = []
    sources: list[dict]      = []
    rewritten_query          = req.message
    confidence               = 1.0

    # Long-term memory (past session summaries)
    lt_memory = get_long_term_memory_context()
    if lt_memory:
        context_parts.append(lt_memory)

    if is_progress_question(req.message):
        logger.info(f"Progress route → DB: '{req.message[:60]}'")
        context_parts.append(build_progress_context(req.message))

    elif req.use_rag:
        # Pass last 6 messages for reference resolution ("explain that" works)
        conv_history = [{"role": m.role, "content": m.content} for m in session.messages[-6:]]

        rag_context, rewritten_query, confidence, chunks = await build_context(
            req.message,
            topic=req.topic,
            conversation_history=conv_history,
        )
        if rag_context:
            context_parts.append(rag_context)
        sources = [
            {
                "content":      c["content"][:200],
                "score":        c.get("score", 0),
                "heading_path": c.get("metadata",{}).get("heading_path",""),
                "source_file":  c.get("metadata",{}).get("source_path","").split("/")[-1],
            }
            for c in chunks
        ]

    # ── Build prompt ──────────────────────────────────────────────────────────
    if context_parts:
        ctx = "\n\n".join(context_parts)
        if confidence < LOW_CONFIDENCE_THRESHOLD and req.use_rag:
            user_content = (
                f"{ctx}\n\n"
                f"Retrieval confidence is low ({confidence:.0%}). "
                f"The answer was not found in the candidate's notes. "
                f"Start your reply with: 'This wasn't found in your notes — answering from general knowledge:'\n\n"
                f"Question: {req.message}"
            )
        else:
            user_content = (
                f"{ctx}\n\n"
                f"Instructions:\n"
                f"- Cite sources inline using [1][2] etc as listed above\n"
                f"- Use structured markdown\n"
                f"- If something is missing from context say: "
                f"'Not in your notes — from general knowledge:'\n"
                f"- Never hallucinate facts\n\n"
                f"Question: {req.message}"
            )
    else:
        user_content = req.message

    history.append({"role": "user", "content": user_content})
    response_text = await llm.chat(history, model=req.model, mode=req.mode)

    # ── Persist ───────────────────────────────────────────────────────────────
    user_msg = Message(role="user", content=req.message)
    asst_msg = Message(
        role="assistant",
        content=response_text,
        metadata={
            "mode":                 req.mode,
            "rewritten_query":      rewritten_query,
            "retrieval_confidence": round(confidence, 3),
        },
    )
    session.messages.extend([user_msg, asst_msg])
    if len(session.messages) == 2:
        session.title = req.message[:60] + ("…" if len(req.message) > 60 else "")
    repo.save(session)

    try:
        await maybe_summarize(session.id, session.messages, session.topic)
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")

    return ChatResponse(
        session_id=session.id,
        message=asst_msg,
        sources=sources,
        model_used=req.model or settings.DEFAULT_MODEL,
    )


@router.get("/sessions")
async def list_sessions():
    return SessionRepository().list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = SessionRepository().load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    return {"deleted": SessionRepository().delete(session_id)}
