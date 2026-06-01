from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api.routes import chat, memory, models, analysis, progress, interview

settings = get_settings()

app = FastAPI(title=settings.APP_NAME, version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(interview.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.7.0"}
