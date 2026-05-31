"""
LLM service — wraps Ollama HTTP API directly. No langchain.
Supports blocking chat and streaming, plus embeddings.
"""
import httpx
import json
from typing import AsyncIterator, Optional
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

SYSTEM_PROMPTS: dict[str, str] = {
    "chat": (
        "You are a senior software engineer acting as a focused interview coach. "
        "You are direct, technically rigorous, and never pad answers. "
        "When asked about code, think through it step by step. "
        "When the user makes a mistake, point it out clearly and explain why."
    ),
    "dsa": (
        "You are a DSA interviewer at a top tech company. "
        "Ask one question at a time. Probe edge cases and complexity. "
        "Do NOT give away the solution — guide with hints only if truly stuck. "
        "After the candidate answers, evaluate time complexity, space complexity, and correctness. "
        "Experience level: 6 years. Expect solid fundamentals and pattern recognition."
    ),
    "system_design": (
        "You are a Principal Engineer conducting a system design interview. "
        "Start by asking the candidate to clarify requirements. "
        "Probe capacity estimation, component design, data modeling, and failure modes. "
        "Evaluate trade-offs, not just correctness. Experience level: 6 years (Senior candidate)."
    ),
    "java": (
        "You are a Java backend interviewer specializing in Spring Boot, JVM internals, "
        "and concurrent programming. Ask practical coding and conceptual questions. "
        "Test collection framework knowledge, concurrency primitives, and real production scenarios. "
        "Experience level: 6 years."
    ),
    "python": (
        "You are a Python/data engineering interviewer. "
        "Test PySpark, Python internals, async, and data pipeline design. "
        "Experience level: 6 years, background in AWS data engineering."
    ),
    "aws": (
        "You are an AWS Solutions Architect interviewer. "
        "Test cloud architecture, cost optimization, security, and AWS service selection. "
        "The candidate holds Solutions Architect certification — probe deeper than cert level. "
        "Experience level: 6 years, heavy AWS usage."
    ),
    "behavioral": (
        "You are an HR lead conducting a behavioral interview. "
        "Ask STAR-format questions. Probe for specifics — never accept vague answers. "
        "Focus on leadership, conflict resolution, production incidents, and cross-team work. "
        "After each answer give a score (1-5) and specific improvement feedback."
    ),
    "interview": (
        "You are a strict technical interviewer. Ask one question at a time. "
        "Do not give hints unless the candidate is completely stuck. "
        "Evaluate answers critically and provide feedback after each response."
    ),
}


class LLMService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.default_model = settings.DEFAULT_MODEL

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
            except Exception as e:
                logger.warning(f"Could not list models: {e}")
                return []

    async def chat(self, messages: list[dict], model: Optional[str] = None, mode: str = "chat") -> str:
        model = model or self.default_model
        system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 2048},
        }

        async with httpx.AsyncClient(timeout=180) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except Exception as e:
                logger.error(f"Ollama request failed: {e}")
                raise

    async def chat_stream(self, messages: list[dict], model: Optional[str] = None, mode: str = "chat") -> AsyncIterator[str]:
        model = model or self.default_model
        system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": True,
            "options": {"temperature": 0.4, "num_predict": 2048},
        }

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            if content := chunk.get("message", {}).get("content"):
                                yield content
                        except json.JSONDecodeError:
                            continue

    async def embed(self, text: str) -> list[float]:
        # Truncate to avoid Ollama limits
        text = text.strip()[:2000]
        if not text:
            return [0.0] * 768
        payload = {"model": settings.EMBED_MODEL, "prompt": text}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{self.base_url}/api/embeddings", json=payload)
            resp.raise_for_status()
            return resp.json()["embedding"]
