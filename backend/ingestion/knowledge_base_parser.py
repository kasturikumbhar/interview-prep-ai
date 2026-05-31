"""
Knowledge Base Parser — understands the structured MD format from learning conversations.
Extracts mastery levels, topics, breakthrough moments, weaknesses, and roadmap items.
This is NOT generic chunking — it parses the specific artifact structure.
"""
import re
from pathlib import Path
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

# Mastery keywords mapped to score
MASTERY_MAP = {
    "strong": 5,
    "mastered": 5,
    "internalized": 4,
    "intermediate": 3,
    "introduced": 2,
    "not yet covered": 1,
    "not internalized": 2,
    "struggling": 2,
    "weak": 2,
}

# Topic → category mapping
TOPIC_CATEGORY_MAP = {
    # DSA
    "sliding window": "dsa", "two pointers": "dsa", "binary search": "dsa",
    "dynamic programming": "dsa", "dp": "dsa", "backtracking": "dsa",
    "graph": "dsa", "tree": "dsa", "heap": "dsa", "trie": "dsa",
    "union find": "dsa", "topological": "dsa", "greedy": "dsa",
    "monotonic stack": "dsa", "linked list": "dsa", "recursion": "dsa",
    "sorting": "dsa", "bit manipulation": "dsa",
    # System Design
    "system design": "system_design", "distributed": "system_design",
    "database": "system_design", "caching": "system_design", "api design": "system_design",
    "load balancing": "system_design", "microservices": "system_design",
    "message queue": "system_design", "kafka": "system_design",
    # Java
    "java": "java", "spring": "java", "jvm": "java", "concurrency": "java",
    "thread": "java", "collections": "java", "stream": "java",
    # Python
    "python": "python", "pyspark": "python", "spark": "python",
    "pandas": "python", "async": "python", "generator": "python",
    # AWS
    "aws": "aws", "s3": "aws", "lambda": "aws", "glue": "aws",
    "kinesis": "aws", "dynamodb": "aws", "ec2": "aws", "ecs": "aws",
    "step functions": "aws", "sqs": "aws", "sns": "aws",
    # Behavioral
    "behavioral": "behavioral", "star": "behavioral", "leadership": "behavioral",
    "conflict": "behavioral", "production incident": "behavioral",
}


def detect_category(text: str) -> str:
    text_lower = text.lower()
    for keyword, category in TOPIC_CATEGORY_MAP.items():
        if keyword in text_lower:
            return category
    return "general"


def parse_mastery_section(content: str) -> list[dict]:
    """
    Extract mastery entries from the 'Current Mastery Status' section.
    Handles formats like:
      - Binary Search: Strong
      - **Sliding Window** — Intermediate
      - Tree DFS - introduced but not internalized
    """
    entries = []
    # Find mastery section
    mastery_match = re.search(
        r"(?:Current Mastery Status|Mastery Status)(.*?)(?=\n##|\Z)",
        content, re.IGNORECASE | re.DOTALL
    )
    if not mastery_match:
        return entries

    section = mastery_match.group(1)
    lines = section.split("\n")

    for line in lines:
        line = line.strip().lstrip("- *•").strip()
        if not line:
            continue

        # Try to split on common delimiters: :, —, -, –
        for delimiter in [":", "—", " - ", " – "]:
            if delimiter in line:
                parts = line.split(delimiter, 1)
                topic = parts[0].strip().strip("*_").strip()
                mastery_text = parts[1].strip().lower() if len(parts) > 1 else ""

                if len(topic) < 3 or len(topic) > 80:
                    continue

                mastery_score = 3  # default intermediate
                for keyword, score in MASTERY_MAP.items():
                    if keyword in mastery_text:
                        mastery_score = score
                        break

                category = detect_category(topic)
                entries.append({
                    "topic": topic,
                    "mastery": mastery_score,
                    "mastery_label": mastery_text[:50],
                    "category": category,
                })
                break

    return entries


def parse_topics_covered(content: str) -> list[dict]:
    """Extract topics from 'Topics Covered' section."""
    topics = []
    section_match = re.search(
        r"(?:Topics Covered|## Topics)(.*?)(?=\n##|\Z)",
        content, re.IGNORECASE | re.DOTALL
    )
    if not section_match:
        return topics

    section = section_match.group(1)
    # Extract h3 headers as topic names
    topic_headers = re.findall(r"###\s+(.+)", section)
    for t in topic_headers:
        clean = t.strip().strip("*_").strip()
        if clean:
            topics.append({
                "topic": clean,
                "category": detect_category(clean),
            })

    return topics


def parse_weaknesses(content: str) -> list[str]:
    """Extract weakness/misconception entries."""
    weaknesses = []
    patterns = [
        r"(?:Common Mistakes|Misconceptions|What Does Not Work|Weaknesses?|Struggles?)(.*?)(?=\n##|\Z)",
        r"(?:recurring misconceptions)(.*?)(?=\n##|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            section = match.group(1)
            items = re.findall(r"[-•*]\s+(.+)", section)
            weaknesses.extend([i.strip() for i in items if len(i.strip()) > 10])
            break
    return weaknesses[:10]


def parse_future_roadmap(content: str) -> list[str]:
    """Extract next topics from roadmap section."""
    roadmap = []
    match = re.search(
        r"(?:Future Roadmap|Next Steps|Coaching Continuation|Roadmap)(.*?)(?=\n##|\Z)",
        content, re.IGNORECASE | re.DOTALL
    )
    if match:
        section = match.group(1)
        items = re.findall(r"[-•*]\s+(.+)", section)
        roadmap.extend([i.strip() for i in items if len(i.strip()) > 5])
    return roadmap[:10]


def parse_breakthrough_moments(content: str) -> list[str]:
    """Extract breakthrough/insight moments."""
    breakthroughs = []
    match = re.search(
        r"(?:Breakthrough Moments?|Key Insights?|Finally.Clicked)(.*?)(?=\n##|\Z)",
        content, re.IGNORECASE | re.DOTALL
    )
    if match:
        section = match.group(1)
        items = re.findall(r"[-•*]\s+(.+)", section)
        breakthroughs.extend([i.strip() for i in items if len(i.strip()) > 10])
    return breakthroughs[:10]


def parse_knowledge_base_md(file_path: Path) -> dict:
    """
    Full parse of a knowledge base MD file.
    Returns structured data ready to store in progress DB.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {file_path}: {e}")
        return {}

    # Detect if this is a knowledge base artifact
    is_kb = any(marker in content for marker in [
        "Current Mastery Status", "Topics Covered", "Knowledge Base",
        "Mastery Status", "Learning Objectives", "Problem-Solving Frameworks"
    ])
    is_mentor = any(marker in content for marker in [
        "Mentor Profile", "Student Profile", "Coaching Continuation",
        "Behavioral Patterns", "Teaching Instructions"
    ])

    if not (is_kb or is_mentor):
        return {}

    result = {
        "file": str(file_path),
        "type": "knowledge_base" if is_kb else "mentor_profile",
        "mastery_entries": parse_mastery_section(content),
        "topics_covered": parse_topics_covered(content),
        "weaknesses": parse_weaknesses(content),
        "future_roadmap": parse_future_roadmap(content),
        "breakthrough_moments": parse_breakthrough_moments(content),
        "raw_length": len(content),
    }

    logger.info(
        f"Parsed KB: {file_path.name} → "
        f"{len(result['mastery_entries'])} mastery entries, "
        f"{len(result['topics_covered'])} topics, "
        f"{len(result['weaknesses'])} weaknesses"
    )
    return result
