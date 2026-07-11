from fastapi import APIRouter, HTTPException
from app.models.chat import ChatRequest, ChatResponse, Message, Session
from app.services.llm_service import LLMService
from app.services.retrieval_service import build_context
from app.services.progress_service import is_progress_question, build_progress_context
from app.services.session_summary_service import maybe_summarize, get_long_term_memory_context
from app.repositories.session_repository import SessionRepository
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
settings = get_settings()


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest):
    llm  = LLMService()
    repo = SessionRepository()

    session = repo.load(req.session_id) if req.session_id else None
    if not session:
        session = Session(topic=req.topic, mode=req.mode)

    history = [{"role": m.role, "content": m.content} for m in session.messages[-20:]]

    # ── Build context ─────────────────────────────────────────────────────────
    context_parts = []
    sources = []
    rewritten_query = req.message

    # Long-term memory from past sessions
    lt_memory = get_long_term_memory_context()
    if lt_memory:
        context_parts.append(lt_memory)

    # Route: progress questions → SQLite DB, knowledge questions → hybrid RAG
    if is_progress_question(req.message):
        logger.info(f"Progress question → DB: '{req.message[:60]}'")
        context_parts.append(build_progress_context(req.message))
    elif req.use_rag:
        # Use full retrieval pipeline: rewrite → classify → BM25+dense → rerank
        rag_context, rewritten_query = await build_context(req.message, topic=req.topic)
        if rag_context:
            context_parts.append(rag_context)
            # Show sources for transparency
            try:
                from app.services.retrieval_service import retrieve
                chunks, _ = await retrieve(req.message, topic=req.topic, k_final=3)
                sources = [{"content": c["content"][:200], "score": c.get("score", 0)} for c in chunks]
            except Exception:
                pass

    # ── Assemble prompt ───────────────────────────────────────────────────────
    if context_parts:
        context_block = "\n\n".join(context_parts)
        user_content = (
            f"{context_block}\n\n"
            f"Use structured progress data directly when available. "
            f"Use retrieved context as evidence — cite specific concepts. "
            f"Do not invent facts not present in the context. "
            f"If information is missing, say so.\n\n"
            f"Question: {req.message}"
        )
        if rewritten_query != req.message:
            logger.info(f"Query rewritten: '{req.message[:40]}' → '{rewritten_query[:60]}'")
    else:
        user_content = req.message

    history.append({"role": "user", "content": user_content})

    response_text = await llm.chat(history, model=req.model, mode=req.mode)

    # ── Persist ───────────────────────────────────────────────────────────────
    user_msg      = Message(role="user", content=req.message)
    assistant_msg = Message(
        role="assistant", content=response_text,
        metadata={"mode": req.mode, "rewritten_query": rewritten_query},
    )
    session.messages.extend([user_msg, assistant_msg])
    if len(session.messages) == 2:
        session.title = req.message[:60] + ("…" if len(req.message) > 60 else "")
    repo.save(session)

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
