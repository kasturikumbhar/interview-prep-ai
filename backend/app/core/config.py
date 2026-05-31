from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "Interview Prep AI"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    DEFAULT_MODEL: str = "qwen2.5-coder:7b"
    EMBED_MODEL: str = "nomic-embed-text"

    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION_PREFIX: str = "iprep"

    DATA_DIR: str = "./data"
    NOTES_DIR: str = "./data/notes"
    SESSIONS_DIR: str = "./data/sessions"

    DEFAULT_RETRIEVAL_K: int = 5
    CHUNK_SIZE: int = 600
    CHUNK_OVERLAP: int = 80

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
