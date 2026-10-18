"""
Ingestion cache — MD5 hash per file so unchanged files are skipped on re-ingest.
Stored at data/ingestion_cache.json.

Why this matters: without caching, every `ingest.py` run re-embeds every file.
With 200 notes files and mxbai-embed-large, that's 10-20 minutes wasted.
With caching, only new or changed files are embedded.
"""
import json
import hashlib
from pathlib import Path

# Resolved at runtime via settings — default fallback keeps it working standalone
try:
    from app.core.config import get_settings
    _DATA_DIR = Path(get_settings().DATA_DIR)
except Exception:
    _DATA_DIR = Path("./data")

CACHE_PATH = _DATA_DIR / "ingestion_cache.json"


def _load() -> dict[str, str]:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(cache: dict[str, str]):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def file_hash(path: Path) -> str:
    """MD5 of file contents."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def is_unchanged(path: Path) -> bool:
    """Return True if file has not changed since last ingest."""
    cache = _load()
    try:
        return cache.get(str(path)) == file_hash(path)
    except Exception:
        return False


def mark_ingested(path: Path):
    """Record file hash after successful ingest."""
    cache = _load()
    try:
        cache[str(path)] = file_hash(path)
        _save(cache)
    except Exception as e:
        print(f"Warning: cache write failed for {path}: {e}")


def clear_cache():
    """Delete the cache file — forces full re-ingest next run."""
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    print("Ingestion cache cleared.")
