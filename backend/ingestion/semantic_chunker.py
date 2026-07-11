"""
Semantic Chunker — replaces fixed-size chunking.

Strategy:
- Split on markdown headers first (preserves concept boundaries)
- Keep parent header hierarchy as metadata
- Preserve code blocks, tables, lists intact — never split them
- Merge tiny sections (<100 chars) into parent
- Split oversized sections (>1200 chars) on paragraph boundaries
- One concept per chunk

This directly fixes the symptom: qwen2.5 giving generic answers because
chunks mixed unrelated topics (e.g. Kafka producer + consumer in one chunk).
"""
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

MIN_CHUNK_SIZE = 80     # below this, merge into parent
MAX_CHUNK_SIZE = 1200   # above this, split on paragraph boundary
IDEAL_CHUNK_SIZE = 600


@dataclass
class SemanticChunk:
    content: str
    heading: str               # immediate section heading
    parent_heading: str        # parent section heading (for context)
    heading_path: str          # full path e.g. "Kafka > Consumer Groups > Rebalance"
    chunk_id: str
    document_id: str
    source_file: str
    topic: str                 # dsa | system_design | java | python | aws | behavioral | general
    subcategory: str           # e.g. "Heap" for dsa, "Kafka" for system_design
    difficulty: str            # easy | medium | hard | unknown
    chunk_type: str            # text | code | table | star_story | problem
    metadata: dict = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict:
        return {
            "heading": self.heading,
            "parent_heading": self.parent_heading,
            "heading_path": self.heading_path,
            "source_file": self.source_file,
            "topic": self.topic,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty,
            "chunk_type": self.chunk_type,
            "document_id": self.document_id,
            **self.metadata,
        }


def _make_chunk_id(content: str, source_file: str) -> str:
    return hashlib.md5(f"{source_file}:{content[:100]}".encode()).hexdigest()[:16]


def _make_doc_id(source_file: str) -> str:
    return hashlib.md5(source_file.encode()).hexdigest()[:16]


def _detect_chunk_type(content: str) -> str:
    if content.strip().startswith("```"):
        return "code"
    if "|---" in content or "| ---" in content:
        return "table"
    if re.search(r"(?:Situation|Task|Action|Result):", content, re.IGNORECASE):
        return "star_story"
    if re.search(r"(?:time complexity|space complexity|leetcode|def \w+\(|class Solution)", content, re.IGNORECASE):
        return "problem"
    return "text"


def _detect_difficulty(content: str, heading: str) -> str:
    combined = (content + " " + heading).lower()
    if "hard" in combined:
        return "hard"
    if "medium" in combined:
        return "medium"
    if "easy" in combined:
        return "easy"
    return "unknown"


def _detect_subcategory(heading: str, content: str, topic: str) -> str:
    """Extract subcategory from heading hierarchy."""
    # Use the immediate heading as subcategory
    clean = re.sub(r"^#+\s*", "", heading).strip()
    if clean:
        return clean[:60]
    return topic


def _split_on_paragraphs(text: str, max_size: int = MAX_CHUNK_SIZE) -> list[str]:
    """Split oversized text on paragraph boundaries, respecting code blocks."""
    if len(text) <= max_size:
        return [text]

    # Protect code blocks — don't split inside them
    code_block_re = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    blocks = []
    pos = 0
    for m in code_block_re.finditer(text):
        if text[pos:m.start()].strip():
            blocks.append(("text", text[pos:m.start()]))
        blocks.append(("code", m.group()))
        pos = m.end()
    if text[pos:].strip():
        blocks.append(("text", text[pos:]))

    # Now split text segments on double newlines
    chunks = []
    current = ""
    for btype, bcontent in blocks:
        if btype == "code":
            if len(current) + len(bcontent) > max_size and current.strip():
                chunks.append(current.strip())
                current = bcontent
            else:
                current += "\n\n" + bcontent
        else:
            paragraphs = re.split(r"\n\n+", bcontent)
            for para in paragraphs:
                if len(current) + len(para) > max_size and current.strip():
                    chunks.append(current.strip())
                    current = para
                else:
                    current += "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]


def _parse_headers(text: str) -> list[dict]:
    """
    Parse markdown into sections by header.
    Returns list of {level, heading, content} dicts.
    """
    # Match headers (# ## ### etc)
    header_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    sections = []
    positions = [(m.start(), m.group(1), m.group(2)) for m in header_re.finditer(text)]

    if not positions:
        # No headers — treat whole document as one section
        return [{"level": 0, "heading": "", "content": text}]

    # Content before first header
    if positions[0][0] > 0:
        preamble = text[:positions[0][0]].strip()
        if preamble:
            sections.append({"level": 0, "heading": "", "content": preamble})

    for i, (pos, hashes, heading) in enumerate(positions):
        level = len(hashes)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        # Content = everything after the header line until next header
        header_end = text.index("\n", pos) + 1 if "\n" in text[pos:] else len(text)
        content = text[header_end:end].strip()
        sections.append({"level": level, "heading": heading.strip(), "content": content})

    return sections


def chunk_markdown(
    text: str,
    source_file: str,
    topic: str = "general",
) -> list[SemanticChunk]:
    """
    Main entry point. Converts a markdown document into semantic chunks.
    """
    doc_id = _make_doc_id(source_file)
    sections = _parse_headers(text)
    chunks: list[SemanticChunk] = []

    # Build heading stack for parent tracking
    heading_stack: list[tuple[int, str]] = []  # (level, heading)

    for section in sections:
        level = section["level"]
        heading = section["heading"]
        content = section["content"]

        # Update heading stack
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()

        parent_heading = heading_stack[-1][1] if heading_stack else ""
        heading_path = " > ".join(h for _, h in heading_stack) + (f" > {heading}" if heading else "")
        heading_path = heading_path.lstrip(" > ")

        if heading:
            heading_stack.append((level, heading))

        if not content.strip():
            continue

        # Skip tiny sections — merge concept into heading only if truly minimal
        if len(content.strip()) < MIN_CHUNK_SIZE and not re.search(r"```", content):
            # Absorb into previous chunk if exists
            if chunks:
                chunks[-1] = SemanticChunk(
                    content=chunks[-1].content + f"\n\n**{heading}**\n{content}",
                    heading=chunks[-1].heading,
                    parent_heading=chunks[-1].parent_heading,
                    heading_path=chunks[-1].heading_path,
                    chunk_id=chunks[-1].chunk_id,
                    document_id=doc_id,
                    source_file=source_file,
                    topic=topic,
                    subcategory=chunks[-1].subcategory,
                    difficulty=chunks[-1].difficulty,
                    chunk_type=chunks[-1].chunk_type,
                )
                continue

        # Split oversized content
        sub_contents = _split_on_paragraphs(content, MAX_CHUNK_SIZE)

        for sub_content in sub_contents:
            if not sub_content.strip():
                continue

            full_content = f"## {heading}\n\n{sub_content}" if heading else sub_content

            chunk = SemanticChunk(
                content=full_content,
                heading=heading,
                parent_heading=parent_heading,
                heading_path=heading_path,
                chunk_id=_make_chunk_id(full_content, source_file),
                document_id=doc_id,
                source_file=source_file,
                topic=topic,
                subcategory=_detect_subcategory(heading, sub_content, topic),
                difficulty=_detect_difficulty(sub_content, heading),
                chunk_type=_detect_chunk_type(sub_content),
            )
            chunks.append(chunk)

    logger.info(f"Semantic chunked {source_file}: {len(chunks)} chunks from {len(sections)} sections")
    return chunks


def chunk_resume(text: str, source_file: str) -> list[SemanticChunk]:
    """
    Resume-specific chunking: Summary / Experience / Each Project / Skills / Education.
    """
    return chunk_markdown(text, source_file, topic="general")


def chunk_star_stories(text: str, source_file: str) -> list[SemanticChunk]:
    """
    Behavioral: one STAR story per chunk.
    Splits on story separators (--- or ## Story Title patterns).
    """
    # Try splitting on horizontal rules or h2/h3 headers
    story_re = re.compile(r"(?:^|\n)(?:---+|#{2,3}\s+.+)\n", re.MULTILINE)
    parts = story_re.split(text)
    headers = [m.group().strip() for m in story_re.finditer(text)]

    if len(parts) <= 1:
        return chunk_markdown(text, source_file, topic="behavioral")

    chunks = []
    doc_id = _make_doc_id(source_file)
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        heading = headers[i - 1].lstrip("#").strip() if i > 0 and i - 1 < len(headers) else f"Story {i}"
        full_content = f"## {heading}\n\n{part}"
        chunks.append(SemanticChunk(
            content=full_content,
            heading=heading,
            parent_heading="Behavioral Stories",
            heading_path=f"Behavioral > {heading}",
            chunk_id=_make_chunk_id(full_content, source_file),
            document_id=doc_id,
            source_file=source_file,
            topic="behavioral",
            subcategory=heading,
            difficulty="unknown",
            chunk_type="star_story",
        ))
    return chunks
