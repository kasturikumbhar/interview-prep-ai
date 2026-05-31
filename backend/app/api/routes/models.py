from fastapi import APIRouter
from app.services.llm_service import LLMService

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/")
async def list_models():
    return {"models": await LLMService().list_models()}


@router.get("/health")
async def health():
    models = await LLMService().list_models()
    return {"status": "ok" if models else "ollama_unavailable", "models_available": models}
