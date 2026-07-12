from fastapi import APIRouter, HTTPException
from app.models.chat import ChatRequest, ChatResponse, Message, Session
from app.services.llm_service import LLMService
from app.services.retrieval_service import build_context
from app.services.progress_service import is_progress_question, build_progress_context
from app.services.session_summary_service import (
    maybe_summarize, get_long_term_memory_context,
)
from app.repositories.session_repository import SessionRepository
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
settings = get_settings()

# Confidence below this → answer from LLM general knowledge with disclosure
LOW_CONFIDENCE_THRESHOLD = 0.35


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest):
    llm  = LLMService()
    repo = SessionRepository()

    # Load or create session
    session = repo.load(req.session_id) if req.session_id else None
    if not session:
        session = Session(topic=req.topic, mode=req.mode)

    # Build history for LLM (last 20 messages)
    history = [
        {"role": m.role, "content": m.content}
        for m in session.messages[-20:]
    ]

    # ── Context assembly ──────────────────────────────────────────────────────
    context_parts: list[str] = []
    sources:       list[dict] = []
    rewritten_query = req.message
    confidence      = 1.0

    # 1. Long-term memory (past session summaries)
    lt_memory = get_long_term_memory_context()
    if lt_memory:
        context_parts.append(lt_memory)

    # 2. Route: progress questions → SQLite, knowledge → hybrid RAG
    if is_progress_question(req.message):
        logger.info(f"Progress route → DB: '{req.message[:60]}'")
        context_parts.append(build_progress_context(req.message))

    elif req.use_rag:
        # Pass conversation history for reference resolution
        # ("explain that more" → resolves to previous topic)
        conv_history = [
            {"role": m.role, "content": m.content}
            for m in session.messages[-6:]
        ]

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
                    "heading_path": c.get("metadata", {}).get("heading_path", ""),
                    "source_file":  c.get("metadata", {}).get("source_path", "")
                                     .split("/")[-1],
                }
                for c in chunks
            ]

        if confidence < LOW_CONFIDENCE_THRESHOLD:
            logger.info(
                f"Low retrieval confidence ({confidence:.2f}) for: '{req.message[:60]}'"
            )

    # ── Prompt assembly ───────────────────────────────────────────────────────
    if context_parts:
        context_block = "\n\n".join(context_parts)

        if confidence < LOW_CONFIDENCE_THRESHOLD and req.use_rag:
            # Low confidence — answer from general knowledge, disclose it
            user_content = (
                f"{context_block}\n\n"
                f"The retrieval system did not find strong matches in the candidate's "
                f"personal notes (confidence: {confidence:.0%}). "
                f"Answer from your general technical knowledge and explicitly say: "
                f"'This wasn't found in your notes — answering from general knowledge:'\n\n"
                f"Question: {req.message}"
            )
        else:
            user_content = (
                f"{context_block}\n\n"
                f"Instructions:\n"
                f"- Use the retrieved context as your primary source\n"
                f"- Cite sources inline using [1], [2] etc as shown in the context\n"
                f"- If something is not in the context, say "
                f"'This wasn't in your notes — from general knowledge:' before answering\n"
                f"- Use structured markdown in your response\n"
                f"- Do not hallucinate facts\n\n"
                f"Question: {req.message}"
            )
    else:
        user_content = req.message

    history.append({"role": "user", "content": user_content})

    # ── LLM generation ────────────────────────────────────────────────────────
    response_text = await llm.chat(history, model=req.model, mode=req.mode)

    # ── Persist ───────────────────────────────────────────────────────────────
    user_msg = Message(role="user", content=req.message)
    assistant_msg = Message(
        role="assistant",
        content=response_text,
        metadata={
            "mode":             req.mode,
            "rewritten_query":  rewritten_query,
            "retrieval_confidence": round(confidence, 3),
        },
    )
    session.messages.extend([user_msg, assistant_msg])

    if len(session.messages) == 2:
        session.title = req.message[:60] + ("…" if len(req.message) > 60 else "")

    repo.save(session)

    # Async session summarization every N messages
    try:
        await maybe_summarize(session.id, session.messages, session.topic)
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")

    return ChatResponse(
        session_id=session.id,
        message=assistant_msg,
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