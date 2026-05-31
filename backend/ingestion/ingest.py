#!/usr/bin/env python3
"""
Enhanced ingestion script.
- DSA solution files (.py, .java): extracts pattern, difficulty, problem name → SQLite
- Knowledge Base MD files: extracts mastery, weaknesses, roadmap → SQLite
- All files: chunks → ChromaDB for RAG
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
from app.core.config import get_settings
from app.core.logging import get_logger
from ingestion.knowledge_base_parser import parse_knowledge_base_md, detect_category

settings = get_settings()
logger = get_logger("ingestion")

CHUNK_SIZE = settings.CHUNK_SIZE
CHUNK_OVERLAP = settings.CHUNK_OVERLAP

TOPIC_HINTS = {
    "dsa": "dsa", "leetcode": "dsa", "system_design": "system_design",
    "design": "system_design", "java": "java", "spring": "java",
    "python": "python", "pyspark": "python", "spark": "python",
    "aws": "aws", "cloud": "aws", "behavioral": "behavioral",
    "star": "behavioral", "projects": "projects",
}

PATTERN_KEYWORDS = {
    "Sliding Window": ["sliding window", "window size", "max window", "min window"],
    "Two Pointers": ["two pointer", "left, right", "l, r =", "l=0", "two_pointer"],
    "Fast Slow Pointers": ["slow", "fast", "floyd", "cycle detection", "slow = slow.next"],
    "Merge Intervals": ["merge interval", "intervals.sort", "overlap"],
    "Binary Search": ["binary search", "l+(r-l)//2", "mid = ", "bisect"],
    "Tree BFS": ["level order", "collections.deque", "bfs", "queue.append"],
    "Tree DFS": ["dfs", "inorder", "preorder", "postorder"],
    "Graph BFS": ["graph", "visited", "queue", "bfs"],
    "Graph DFS": ["dfs", "visited", "adjacency"],
    "Topological Sort": ["topological", "indegree", "in_degree", "kahn"],
    "Backtracking": ["backtrack", "path.append", "path.pop", "candidates"],
    "Heap": ["heapq", "heappush", "heappop", "nlargest", "nsmallest"],
    "Two Heaps": ["max_heap", "min_heap", "median"],
    "Greedy": ["greedy", "local optimum"],
    "Dynamic Programming 1D": ["dp[i]", "dp =", "memo", "memoization"],
    "Dynamic Programming 2D": ["dp[i][j]", "dp = [["],
    "Trie": ["trie", "TrieNode", "children", "prefix"],
    "Union Find": ["union find", "disjoint", "parent[", "find("],
    "Monotonic Stack": ["monotonic", "mono_stack", "increasing stack"],
}

DIFFICULTY_HINTS = {
    "Easy": ["easy", "#easy", "difficulty: easy"],
    "Medium": ["medium", "#medium", "difficulty: medium"],
    "Hard": ["hard", "#hard", "difficulty: hard"],
}

LC_RE = re.compile(r"(?:leetcode|lc)[#\s]*(\d+)|#(\d+)", re.IGNORECASE)
COMPLEXITY_RE = re.compile(r"Time:\s*O\(([^)]+)\)", re.IGNORECASE)


def detect_topic(path: str) -> str:
    path_lower = path.lower()
    for hint, topic in TOPIC_HINTS.items():
        if hint in path_lower:
            return topic
    return "general"


def extract_dsa_metadata(content: str, filename: str) -> dict:
    content_lower = content.lower()
    problem_name = Path(filename).stem.replace("_", " ").replace("-", " ").title().strip()

    pattern = None
    for p, keywords in PATTERN_KEYWORDS.items():
        if any(kw in content_lower for kw in keywords):
            pattern = p
            break

    difficulty = "Medium"
    for diff, hints in DIFFICULTY_HINTS.items():
        if any(h in content_lower for h in hints):
            difficulty = diff
            break

    lc_match = LC_RE.search(content)
    lc_number = int(lc_match.group(1) or lc_match.group(2)) if lc_match else None

    time_match = COMPLEXITY_RE.search(content)
    time_complexity = f"O({time_match.group(1)})" if time_match else None

    ext = Path(filename).suffix
    language = {".py": "python", ".java": "java", ".js": "javascript"}.get(ext, "python")

    return {
        "problem_name": problem_name,
        "pattern": pattern,
        "difficulty": difficulty,
        "leetcode_number": lc_number,
        "time_complexity": time_complexity,
        "language": language,
    }


def chunk_text(text: str) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) < CHUNK_SIZE:
            current += para + "\n\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            overlap = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else current
            current = overlap + para + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


async def ingest_file(
    path: Path,
    memory: MemoryService,
    progress: ProgressRepository,
    topic: str = None,
    source: str = "notes",
) -> int:
    if path.suffix not in (".md", ".txt", ".py", ".java", ".rst"):
        return 0

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
        return 0

    if not content.strip():
        return 0

    resolved_topic = topic or detect_topic(str(path))

    # ── Knowledge Base MD: parse structure → SQLite ──────────────────────────
    if path.suffix == ".md":
        kb_data = parse_knowledge_base_md(path)
        if kb_data:
            # Store mastery entries
            for entry in kb_data.get("mastery_entries", []):
                progress.upsert_topic_mastery(
                    topic_name=entry["topic"],
                    category=entry["category"],
                    mastery_score=entry["mastery"],
                    mastery_label=entry["mastery_label"],
                    source_file=str(path),
                )

            # Store weaknesses
            if kb_data.get("weaknesses"):
                cat = detect_category(path.stem) or resolved_topic
                progress.save_kb_weaknesses(kb_data["weaknesses"], cat, str(path))

            # Store roadmap items
            if kb_data.get("future_roadmap"):
                cat = detect_category(path.stem) or resolved_topic
                progress.save_roadmap_items(kb_data["future_roadmap"], cat, str(path))

            logger.info(
                f"  → KB parsed: {len(kb_data.get('mastery_entries', []))} mastery, "
                f"{len(kb_data.get('weaknesses', []))} weaknesses, "
                f"{len(kb_data.get('future_roadmap', []))} roadmap items"
            )

    # ── DSA solution files (.py, .java): extract metadata → SQLite ───────────
    elif resolved_topic == "dsa" and path.suffix in (".py", ".java"):
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
            logger.info(f"  → DSA: {meta['problem_name']} | {meta['pattern']} | {meta['difficulty']}")
        except Exception as e:
            logger.warning(f"Could not save DSA progress for {path.name}: {e}")

    # ── Chunk everything → ChromaDB ──────────────────────────────────────────
    chunks = chunk_text(content)
    count = 0
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or len(chunk) < 20:
            continue
        try:
            mem_chunk = MemoryChunk(
                content=chunk[:2000],
                topic=resolved_topic,
                source=source,
                source_path=str(path),
                tags=[path.stem, resolved_topic],
            )
            await memory.ingest(mem_chunk)
            count += 1
        except Exception as e:
            logger.warning(f"Skipped chunk in {path.name}: {e}")

    if count:
        logger.info(f"Ingested {count} chunks from {path.name} → topic={resolved_topic}")
    return count


async def ingest_directory(
    directory: Path,
    memory: MemoryService,
    progress: ProgressRepository,
    topic: str = None,
    source: str = "notes",
) -> int:
    total = 0
    ignore = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}
    for path in sorted(directory.rglob("*")):
        if any(part in ignore for part in path.parts):
            continue
        if path.is_file() and path.suffix in (".md", ".txt", ".py", ".java", ".rst"):
            total += await ingest_file(path, memory, progress, topic, source)
    return total


async def main():
    parser = argparse.ArgumentParser(description="Ingest content into PrepAI")
    parser.add_argument("--source", choices=["notes", "repo", "file"], required=True)
    parser.add_argument("--path", type=str)
    parser.add_argument("--topic", type=str)
    args = parser.parse_args()

    memory = MemoryService()
    progress = ProgressRepository()
    total = 0

    if args.source == "notes":
        notes_dir = Path(settings.NOTES_DIR)
        if not notes_dir.exists():
            print(f"ERROR: {notes_dir} does not exist.")
            sys.exit(1)
        total = await ingest_directory(notes_dir, memory, progress, source="notes")

    elif args.source in ("repo", "file"):
        if not args.path:
            print("ERROR: --path required")
            sys.exit(1)
        p = Path(args.path)
        if not p.exists():
            print(f"ERROR: {p} does not exist")
            sys.exit(1)
        if p.is_dir():
            total = await ingest_directory(p, memory, progress, topic=args.topic, source="repo")
        else:
            total = await ingest_file(p, memory, progress, topic=args.topic, source="file")

    # Final report
    chroma_stats = memory.collection_stats()
    summary = progress.get_full_summary()
    mastery = progress.get_mastery_summary()

    print(f"\n✅ Ingested {total} chunks into ChromaDB")
    print("\n📊 ChromaDB collections:")
    for t, c in chroma_stats.items():
        if c > 0:
            print(f"   {t:<20} → {c} chunks")

    print(f"\n🧠 Progress DB:")
    print(f"   DSA problems tracked : {summary['total_problems']}")
    print(f"   Patterns found       : {list(summary['patterns_covered'].keys())}")
    print(f"   Missing patterns     : {summary['missing_patterns']}")

    if mastery:
        print(f"\n📚 Mastery by topic:")
        for cat, data in mastery.items():
            print(f"   {cat:<20} → {data['topic_count']} topics, avg mastery {data['avg_mastery']}/5")
            if data['weak_topics']:
                print(f"      Weak: {data['weak_topics'][:3]}")


if __name__ == "__main__":
    asyncio.run(main())
