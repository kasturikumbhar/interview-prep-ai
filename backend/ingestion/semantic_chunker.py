"""
Semantic Chunker — replaces fixed-size chunking.

Strategy:
- Split on markdown headers (preserves concept boundaries)
- Keep parent header hierarchy as metadata (heading_path)
- Preserve code blocks, tables, lists intact — never split them
- Merge tiny sections (<80 chars) into parent
- Split oversized sections (>1200 chars) on paragraph boundaries
- One concept per chunk

Fixes: qwen giving generic answers because fixed 600-char chunks
mixed unrelated topics in the same chunk.
"""
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

MIN_CHUNK_SIZE  = 80
MAX_CHUNK_SIZE  = 1200


@dataclass
class SemanticChunk:
    content:        str
    heading:        str
    parent_heading: str
    heading_path:   str        # e.g. "Kafka > Consumer Groups > Rebalance"
    chunk_id:       str
    document_id:    str
    source_file:    str
    topic:          str
    subcategory:    str
    difficulty:     str        # easy | medium | hard | unknown
    chunk_type:     str        # text | code | table | star_story | problem
    metadata:       dict = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict:
        return {
            "heading":        self.heading,
            "parent_heading": self.parent_heading,
            "heading_path":   self.heading_path,
            "source_file":    self.source_file,
            "topic":          self.topic,
            "subcategory":    self.subcategory,
            "difficulty":     self.difficulty,
            "chunk_type":     self.chunk_type,
            "document_id":    self.document_id,
            "chunk_id":       self.chunk_id,
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
    if re.search(
        r"(?:time complexity|space complexity|leetcode|def \w+\(|class Solution)",
        content, re.IGNORECASE
    ):
        return "problem"
    return "text"


def _detect_difficulty(content: str, heading: str) -> str:
    combined = (content + " " + heading).lower()
    for d in ("hard", "medium", "easy"):
        if d in combined:
            return d
    return "unknown"


def _detect_subcategory(heading: str, topic: str) -> str:
    clean = re.sub(r"^#+\s*", "", heading).strip()
    return clean[:60] if clean else topic


def _split_on_paragraphs(text: str, max_size: int = MAX_CHUNK_SIZE) -> list[str]:
    """Split oversized text on paragraph boundaries, never inside code blocks."""
    if len(text) <= max_size:
        return [text]

    code_re = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    blocks: list[tuple[str, str]] = []
    pos = 0
    for m in code_re.finditer(text):
        if text[pos:m.start()].strip():
            blocks.append(("text", text[pos:m.start()]))
        blocks.append(("code", m.group()))
        pos = m.end()
    if text[pos:].strip():
        blocks.append(("text", text[pos:]))

    chunks: list[str] = []
    current = ""
    for btype, bcontent in blocks:
        if btype == "code":
            if len(current) + len(bcontent) > max_size and current.strip():
                chunks.append(current.strip())
                current = bcontent
            else:
                current += "\n\n" + bcontent
        else:
            for para in re.split(r"\n\n+", bcontent):
                if len(current) + len(para) > max_size and current.strip():
                    chunks.append(current.strip())
                    current = para
                else:
                    current += "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]


def _parse_headers(text: str) -> list[dict]:
    header_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    positions  = [(m.start(), m.group(1), m.group(2)) for m in header_re.finditer(text)]

    if not positions:
        return [{"level": 0, "heading": "", "content": text}]

    sections: list[dict] = []
    if positions[0][0] > 0:
        preamble = text[:positions[0][0]].strip()
        if preamble:
            sections.append({"level": 0, "heading": "", "content": preamble})

    for i, (pos, hashes, heading) in enumerate(positions):
        level    = len(hashes)
        end      = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        nl_pos   = text.find("\n", pos)
        hdr_end  = (nl_pos + 1) if nl_pos != -1 else len(text)
        content  = text[hdr_end:end].strip()
        sections.append({"level": level, "heading": heading.strip(), "content": content})

    return sections


def chunk_markdown(
    text: str,
    source_file: str,
    topic: str = "general",
) -> list[SemanticChunk]:
    doc_id   = _make_doc_id(source_file)
    sections = _parse_headers(text)
    chunks: list[SemanticChunk] = []
    heading_stack: list[tuple[int, str]] = []

    for section in sections:
        level   = section["level"]
        heading = section["heading"]
        content = section["content"]

        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()

        parent_heading = heading_stack[-1][1] if heading_stack else ""
        path_parts     = [h for _, h in heading_stack] + ([heading] if heading else [])
        heading_path   = " > ".join(path_parts)

        if heading:
            heading_stack.append((level, heading))

        if not content.strip():
            continue

        # Merge tiny sections into previous chunk
        if len(content.strip()) < MIN_CHUNK_SIZE and "```" not in content:
            if chunks:
                prev = chunks[-1]
                merged_content = prev.content + f"\n\n**{heading}**\n{content}"
                chunks[-1] = SemanticChunk(
                    content=merged_content,
                    heading=prev.heading,
                    parent_heading=prev.parent_heading,
                    heading_path=prev.heading_path,
                    chunk_id=prev.chunk_id,
                    document_id=doc_id,
                    source_file=source_file,
                    topic=topic,
                    subcategory=prev.subcategory,
                    difficulty=prev.difficulty,
                    chunk_type=prev.chunk_type,
                )
                continue

        for sub in _split_on_paragraphs(content, MAX_CHUNK_SIZE):
            if not sub.strip():
                continue
            full = f"## {heading}\n\n{sub}" if heading else sub
            chunks.append(SemanticChunk(
                content=full,
                heading=heading,
                parent_heading=parent_heading,
                heading_path=heading_path,
                chunk_id=_make_chunk_id(full, source_file),
                document_id=doc_id,
                source_file=source_file,
                topic=topic,
                subcategory=_detect_subcategory(heading, topic),
                difficulty=_detect_difficulty(sub, heading),
                chunk_type=_detect_chunk_type(sub),
            ))

    logger.info(f"Semantic chunked {Path(source_file).name}: {len(chunks)} chunks")
    return chunks


def chunk_resume(text: str, source_file: str) -> list[SemanticChunk]:
    return chunk_markdown(text, source_file, topic="general")


def chunk_star_stories(text: str, source_file: str) -> list[SemanticChunk]:
    """One STAR story per chunk — splits on --- or ## headers."""
    story_re = re.compile(r"(?:^|\n)(?:---+|#{2,3}\s+.+)\n", re.MULTILINE)
    parts    = story_re.split(text)
    headers  = [m.group().strip() for m in story_re.finditer(text)]

    if len(parts) <= 1:
        return chunk_markdown(text, source_file, topic="behavioral")

    doc_id = _make_doc_id(source_file)
    chunks: list[SemanticChunk] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        heading = (
            headers[i - 1].lstrip("#").strip()
            if i > 0 and i - 1 < len(headers)
            else f"Story {i}"
        )
        full = f"## {heading}\n\n{part}"
        chunks.append(SemanticChunk(
            content=full,
            heading=heading,
            parent_heading="Behavioral Stories",
            heading_path=f"Behavioral > {heading}",
            chunk_id=_make_chunk_id(full, source_file),
            document_id=doc_id,
            source_file=source_file,
            topic="behavioral",
            subcategory=heading,
            difficulty="unknown",
            chunk_type="star_story",
        ))
    return chunks
