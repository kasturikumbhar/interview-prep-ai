"""
Observability middleware — logs per-request latency and retrieval timing.
Structured JSON logs so you can grep/tail in production or point Datadog at them.

Shows production thinking during interviews:
- Every request gets a trace_id
- Retrieval sub-steps (rewrite, dense, bm25, rerank) are timed separately
- Slow requests (>5s) are flagged
- Easy to extend with Prometheus counters if needed
"""
import time
import uuid
import json
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

perf_logger = logging.getLogger("prepai.perf")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Logs structured JSON per request: method, path, status, latency_ms, trace_id."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = str(uuid.uuid4())[:8]
        request.state.trace_id = trace_id
        start = time.perf_counter()

        response = await call_next(request)

        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        slow = latency_ms > 5000

        log = {
            "trace_id":   trace_id,
            "method":     request.method,
            "path":       request.url.path,
            "status":     response.status_code,
            "latency_ms": latency_ms,
            "slow":       slow,
        }
        level = logging.WARNING if slow else logging.INFO
        perf_logger.log(level, json.dumps(log))

        response.headers["X-Trace-Id"]    = trace_id
        response.headers["X-Latency-Ms"]  = str(latency_ms)
        return response


# ── Per-step timing context manager ──────────────────────────────────────────
class StepTimer:
    """
    Use inside retrieval pipeline to time individual steps.

    Usage:
        with StepTimer("rerank") as t:
            result = rerank(query, docs)
        print(t.ms)  # → 142.3
    """
    def __init__(self, name: str):
        self.name = name
        self.ms   = 0.0
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.ms = round((time.perf_counter() - self._start) * 1000, 1)
        perf_logger.debug(json.dumps({"step": self.name, "latency_ms": self.ms}))
