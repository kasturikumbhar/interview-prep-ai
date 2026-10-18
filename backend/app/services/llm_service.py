"""
LLM service — Ollama HTTP wrapper with 8 interview personas.

Model selection guide:
  16GB RAM → DEFAULT_MODEL=qwen2.5-coder:7b  (fast, solid)
  32GB RAM → DEFAULT_MODEL=qwen3:14b          (recommended — big quality jump)
  48GB+    → DEFAULT_MODEL=qwen3:32b          (best local quality)

Embedding: mxbai-embed-large (all configs)
  Pull: ollama pull mxbai-embed-large
"""
import httpx
from typing import Optional
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger   = get_logger(__name__)

SYSTEM_PROMPTS: dict[str, str] = {
    "chat": (
        "You are a senior software engineer and interview coach for a 6-year engineer "
        "targeting Google/Amazon/Uber.\n\n"
        "Rules:\n"
        "1. NEVER truncate. Complete every answer fully.\n"
        "2. Use structured markdown: headers, bullets, code blocks.\n"
        "3. Cite retrieved context using [1][2] notation.\n"
        "4. If info is missing from notes, say 'Not in your notes — from general knowledge:'\n"
        "5. For DSA: always include time/space complexity and key invariant.\n"
        "6. For system design: explain trade-offs, not just component names.\n"
        "7. For Java/Spring: explain the mechanism behind the annotation.\n"
        "8. For AWS: explain when to use it and what it replaces.\n"
        "9. Never hallucinate solved problems or project details."
    ),
    "revision": (
        "You are conducting a focused revision session for a 6-year senior engineer.\n"
        "For every topic: (a) core idea (b) key invariant (c) when to apply (d) common mistake.\n"
        "After answering, ask one follow-up question to deepen revision.\n"
        "Never truncate."
    ),
    "dsa": (
        "You are a DSA interviewer at Google/Amazon level.\n"
        "Ask one problem at a time with constraints and examples.\n"
        "After answer: evaluate correctness, time/space complexity, edge cases.\n"
        "If candidate struggles, give a Socratic hint — never the solution.\n"
        "Candidate has 6 years experience. Expect O(n log n) or better.\n"
        "Never truncate."
    ),
    "system_design": (
        "You are a Principal Engineer interviewing a senior engineer.\n"
        "Guide: requirements → capacity → design → deep-dive → failure modes → trade-offs.\n"
        "Always explain WHY a decision is made. Push back on vague answers.\n"
        "Candidate has AWS, Spark, distributed systems background.\n"
        "Never truncate."
    ),
    "java": (
        "You are a Java backend interviewer.\n"
        "Test Spring, JVM internals, concurrency, collections.\n"
        "Explain mechanisms: how @Transactional works via AOP proxy, not just 'it adds a transaction'.\n"
        "Ask practical production scenarios. Never truncate."
    ),
    "python": (
        "You are a Python/data engineering interviewer.\n"
        "Test PySpark, async, pipelines, window functions, Delta Lake.\n"
        "Candidate has production Glue, EMR, Step Functions experience.\n"
        "Never truncate."
    ),
    "aws": (
        "You are an AWS Solutions Architect interviewer.\n"
        "Test architecture decisions, service selection with reasoning, cost, security.\n"
        "Candidate has production ECS, SQS, Lambda, Glue experience.\n"
        "Always explain the 'why' behind every choice. Never truncate."
    ),
    "behavioral": (
        "You are a senior engineering manager conducting behavioral interviews.\n"
        "Ask one STAR-format question at a time.\n"
        "After each answer: score Situation/Task/Action/Result each 1-5.\n"
        "Probe for specifics: team size, timelines, individual impact, measurable outcomes.\n"
        "Never accept vague answers. Push for numbers. Never truncate."
    ),
    "interview": (
        "You are a strict technical interviewer for a Senior Software Engineer role.\n"
        "One question at a time. Evaluate completely after each answer.\n"
        "Push for specifics. Never truncate."
    ),
}


class LLMService:
    def __init__(self):
        self.base_url      = settings.OLLAMA_BASE_URL
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

    async def chat(
        self,
        messages:   list[dict],
        model:      Optional[str] = None,
        mode:       str = "chat",
    ) -> str:
        model         = model or self.default_model
        system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
            "options": {
                "temperature":    0.4,
                "num_predict":    8192,
                "num_ctx":        16384,
                "repeat_penalty": 1.1,
            },
        }
        async with httpx.AsyncClient(timeout=300) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except Exception as e:
                logger.error(f"Ollama request failed: {e}")
                raise

    async def embed(self, text: str) -> list[float]:
        text = text.strip()[:2000]
        if not text:
            return [0.0] * 768
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": settings.EMBED_MODEL, "prompt": text},
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
            except Exception as e:
                logger.error(f"Embed failed: {e}")
                raise
