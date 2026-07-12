"""
Ingestion cache — tracks file hashes to skip re-embedding unchanged files.
Stored as JSON in data/ingestion_cache.json.
"""
import json
import hashlib
from pathlib import Path
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

CACHE_PATH = Path(settings.DATA_DIR) / "ingestion_cache.json"


def _load() -> dict[str, str]:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(cache: dict[str, str]):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def is_unchanged(path: Path) -> bool:
    cache = _load()
    key = str(path)
    try:
        return cache.get(key) == file_hash(path)
    except Exception:
        return False


def mark_ingested(path: Path):
    cache = _load()
    try:
        cache[str(path)] = file_hash(path)
        _save(cache)
    except Exception as e:
        logger.warning(f"Cache write failed for {path}: {e}")


def clear_cache():
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    logger.info("Ingestion cache cleared")