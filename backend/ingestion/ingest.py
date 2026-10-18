#!/usr/bin/env python3
"""
Ingestion script — semantic chunking + MD5 file cache + rich Chroma metadata.

Usage:
    python ingestion/ingest.py --source notes           # incremental (skips unchanged)
    python ingestion/ingest.py --source notes --clear   # clear + full re-ingest
    python ingestion/ingest.py --source notes --force   # force all files
    python ingestion/ingest.py --source repo --path /path/to/DE --topic dsa
    python ingestion/ingest.py --source file --path kafka.md --topic system_design
"""
import asyncio
import argparse
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.memory_service import MemoryService
from app.models.memory import MemoryChunk
from app.repositories.progress_repository import ProgressRepository
from app.repositories.interview_repository import RevisionRepository
from app.core.config import get_settings
from app.core.logging import get_logger
from ingestion.semantic_chunker import (
    chunk_markdown, chunk_resume, chunk_star_stories, SemanticChunk,
)
from ingestion.ingestion_cache import is_unchanged, mark_ingested, clear_cache

try:
    from app.services.retrieval_service import invalidate_bm25_cache
except Exception:
    def invalidate_bm25_cache(): pass

settings = get_settings()
logger   = get_logger("ingestion")

TOPIC_HINTS = {
    "dsa": "dsa", "leetcode": "dsa",
    "system_design": "system_design", "design": "system_design",
    "java": "java", "spring": "java",
    "python": "python", "pyspark": "python", "spark": "python",
    "aws": "aws", "cloud": "aws",
    "behavioral": "behavioral", "star": "behavioral",
    "projects": "projects",
}

PATTERN_KEYWORDS = {
    "Sliding Window":         ["sliding window", "window size"],
    "Two Pointers":           ["two pointer", "l, r =", "l=0"],
    "Fast Slow Pointers":     ["slow", "fast", "cycle detection"],
    "Merge Intervals":        ["merge interval", "intervals.sort"],
    "Binary Search":          ["binary search", "bisect", "l+(r-l)//2"],
    "Tree BFS":               ["level order", "collections.deque"],
    "Tree DFS":               ["dfs", "inorder", "preorder", "postorder"],
    "Graph BFS":              ["visited", "bfs", "queue.append"],
    "Graph DFS":              ["dfs", "visited", "adjacency"],
    "Topological Sort":       ["topological", "indegree", "kahn"],
    "Backtracking":           ["backtrack", "path.append", "path.pop"],
    "Heap":                   ["heapq", "heappush", "heappop"],
    "Two Heaps":              ["max_heap", "min_heap", "median"],
    "Greedy":                 ["greedy"],
    "Dynamic Programming 1D": ["dp[i]", "memo", "memoization"],
    "Dynamic Programming 2D": ["dp[i][j]", "dp = [["],
    "Trie":                   ["trie", "TrieNode"],
    "Union Find":             ["union find", "parent[", "find("],
    "Monotonic Stack":        ["monotonic", "mono_stack"],
}

DIFFICULTY_HINTS = {
    "Easy":   ["easy",   "#easy"],
    "Medium": ["medium", "#medium"],
    "Hard":   ["hard",   "#hard"],
}

LC_RE         = re.compile(r"(?:leetcode|lc)[#\s]*(\d+)|#(\d+)", re.IGNORECASE)
COMPLEXITY_RE = re.compile(r"Time:\s*O\(([^)]+)\)", re.IGNORECASE)
MASTERY_TO_DIFF = {1: "hard", 2: "hard", 3: "medium", 4: "easy", 5: "easy"}


def detect_topic(path: str) -> str:
    pl = path.lower()
    for hint, topic in TOPIC_HINTS.items():
        if hint in pl:
            return topic
    return "general"


def extract_dsa_metadata(content: str, filename: str) -> dict:
    cl = content.lower()
    return {
        "problem_name": Path(filename).stem.replace("_"," ").replace("-"," ").title().strip(),
        "pattern":      next((p for p, kws in PATTERN_KEYWORDS.items()
                              if any(kw in cl for kw in kws)), None),
        "difficulty":   next((d for d, hints in DIFFICULTY_HINTS.items()
                              if any(h in cl for h in hints)), "Medium"),
        "leetcode_number": (lambda m: int(m.group(1) or m.group(2)) if m else None)(
                            LC_RE.search(content)),
        "time_complexity": (lambda m: f"O({m.group(1)})" if m else None)(
                            COMPLEXITY_RE.search(content)),
        "language": {".py": "python", ".java": "java"}.get(
                    Path(filename).suffix, "python"),
    }


async def ingest_semantic_chunks(
    chunks: list[SemanticChunk],
    memory: MemoryService,
    revision: RevisionRepository,
) -> int:
    count = 0
    for chunk in chunks:
        if not chunk.content.strip() or len(chunk.content.strip()) < 20:
            continue
        try:
            mem_chunk = MemoryChunk(
                content=chunk.content[:2000],
                topic=chunk.topic,
                source="notes",
                source_path=chunk.source_file,
                tags=[chunk.subcategory, chunk.topic, chunk.chunk_type],
                metadata=chunk.to_chroma_metadata(),  # rich metadata → Chroma
            )
            await memory.ingest(mem_chunk)

            # Spaced-repetition revision queue
            if chunk.topic in ("dsa","java","python","aws","system_design","behavioral"):
                diff = chunk.difficulty.lower() if chunk.difficulty != "unknown" else "medium"
                revision.upsert(
                    topic=chunk.topic,
                    subtopic=chunk.heading or chunk.subcategory,
                    content=chunk.content[:500],
                    difficulty=diff,
                    source_file=chunk.source_file,
                )
            count += 1
        except Exception as e:
            logger.warning(f"Skipped chunk '{chunk.heading}': {e}")
    return count


async def ingest_file(
    path: Path,
    memory: MemoryService,
    progress: ProgressRepository,
    revision: RevisionRepository,
    topic: str = None,
    force: bool = False,
) -> int:
    if path.suffix not in (".md", ".txt", ".py", ".java", ".rst"):
        return 0

    # MD5 cache — skip unchanged files
    if not force and is_unchanged(path):
        logger.debug(f"Skipping unchanged: {path.name}")
        return 0

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cannot read {path}: {e}")
        return 0

    if not content.strip():
        return 0

    resolved_topic = topic or detect_topic(str(path))

    # ── Choose chunking strategy ──────────────────────────────────────────────
    if path.suffix == ".md":
        is_behavioral = (
            resolved_topic == "behavioral"
            or "star"       in path.stem.lower()
            or "behavioral" in path.stem.lower()
        )
        is_resume = "resume" in path.stem.lower()

        if is_behavioral:
            chunks = chunk_star_stories(content, str(path))
        elif is_resume:
            chunks = chunk_resume(content, str(path))
        else:
            chunks = chunk_markdown(content, str(path), topic=resolved_topic)

    elif path.suffix in (".py", ".java") and resolved_topic == "dsa":
        meta = extract_dsa_metadata(content, path.name)
        try:
            progress.upsert_problem(
                problem_name=meta["problem_name"],
                pattern=meta["pattern"],
                difficulty=meta["difficulty"],
                status="solved",
                language=meta["language"],
                source_file=str(path),
                leetcode_number=meta["leetcode_number"],
                time_complexity=meta["time_complexity"],
            )
            logger.info(
                f"  → DSA: {meta['problem_name']} | "
                f"{meta['pattern']} | {meta['difficulty']}"
            )
        except Exception as e:
            logger.warning(f"DSA progress save failed: {e}")

        wrapped = (
            f"## {meta['problem_name']}\n\n"
            f"Pattern: {meta['pattern']} | Difficulty: {meta['difficulty']}\n\n"
            f"```{meta['language']}\n{content}\n```"
        )
        chunks = chunk_markdown(wrapped, str(path), topic="dsa")

    else:
        wrapped = f"## {path.stem}\n\n```\n{content[:3000]}\n```"
        chunks  = chunk_markdown(wrapped, str(path), topic=resolved_topic)

    count = await ingest_semantic_chunks(chunks, memory, revision)
    logger.info(f"  {path.name}: {count} semantic chunks (topic={resolved_topic})")

    mark_ingested(path)  # save MD5 to cache
    return count


async def ingest_directory(
    directory: Path,
    memory: MemoryService,
    progress: ProgressRepository,
    revision: RevisionRepository,
    topic: str = None,
    force: bool = False,
) -> int:
    total  = 0
    ignore = {"node_modules",".git","__pycache__",".venv","venv","dist","build"}
    for path in sorted(directory.rglob("*")):
        if any(part in ignore for part in path.parts):
            continue
        if path.is_file() and path.suffix in (".md",".txt",".py",".java",".rst"):
            total += await ingest_file(
                path, memory, progress, revision, topic, force=force
            )
    return total


async def main():
    parser = argparse.ArgumentParser(description="PrepAI ingestion — semantic chunking")
    parser.add_argument("--source", choices=["notes","repo","file"], required=True)
    parser.add_argument("--path",  type=str)
    parser.add_argument("--topic", type=str)
    parser.add_argument("--clear", action="store_true",
                        help="Clear ChromaDB collections and ingestion cache")
    parser.add_argument("--force", action="store_true",
                        help="Re-ingest all files even if unchanged")
    args = parser.parse_args()

    memory   = MemoryService()
    progress = ProgressRepository()
    revision = RevisionRepository()
    total    = 0

    if args.clear:
        print("⚠️  Clearing ChromaDB + ingestion cache...")
        clear_cache()
        for t in ["dsa","system_design","java","python","aws",
                  "behavioral","projects","general"]:
            try:
                col = memory._get_or_create_collection(t)
                ids = col.get()["ids"]
                if ids:
                    col.delete(ids=ids)
                    print(f"   Cleared {t}: {len(ids)} chunks")
            except Exception as e:
                print(f"   Could not clear {t}: {e}")

    force = args.force or args.clear

    if args.source == "notes":
        notes_dir = Path(settings.NOTES_DIR)
        if not notes_dir.exists():
            print(f"ERROR: {notes_dir} not found. Run: mkdir -p {notes_dir}")
            sys.exit(1)
        total = await ingest_directory(notes_dir, memory, progress, revision, force=force)

    elif args.source in ("repo", "file"):
        if not args.path:
            print("ERROR: --path required"); sys.exit(1)
        p = Path(args.path)
        if not p.exists():
            print(f"ERROR: {p} not found"); sys.exit(1)
        if p.is_dir():
            total = await ingest_directory(
                p, memory, progress, revision, topic=args.topic, force=force
            )
        else:
            total = await ingest_file(
                p, memory, progress, revision, topic=args.topic, force=force
            )

    invalidate_bm25_cache()

    # ── Final report ──────────────────────────────────────────────────────────
    chroma_stats = memory.collection_stats()
    summary      = progress.get_full_summary()
    mastery      = progress.get_mastery_summary()

    print(f"\n✅  Ingested {total} semantic chunks")
    print("\n📊  ChromaDB collections:")
    for t, c in chroma_stats.items():
        if c > 0:
            print(f"   {t:<20} → {c} chunks")

    print(f"\n🧠  DSA Progress: {summary['total_problems']} problems")
    if summary.get("patterns_covered"):
        print(f"    Patterns: {list(summary['patterns_covered'].keys())}")
    if summary.get("missing_patterns"):
        print(f"    Missing:  {summary['missing_patterns'][:5]}")

    if mastery:
        print(f"\n📚  Mastery by topic:")
        for cat, data in mastery.items():
            print(f"   {cat:<20} → {data['topic_count']} topics, "
                  f"avg {data['avg_mastery']}/5")


if __name__ == "__main__":
    asyncio.run(main())
