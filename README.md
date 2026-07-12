# PrepAI — Personal Interview Preparation OS

> Local-first AI interview coaching with production-grade RAG.
---

## What makes this different from a generic chatbot

| Feature | Generic RAG | PrepAI v12 |
|---|---|---|
| Chunking | Fixed 600-char splits | Semantic markdown chunking (one concept per chunk) |
| Retrieval | Dense embeddings only | Hybrid BM25 + dense → RRF fusion |
| Reranking | None | bge-reranker-base cross-encoder on Apple Silicon MPS |
| Query handling | Raw query | Rewriting + conversational reference resolution |
| Follow-ups | "explain that" breaks | Resolved via conversation history |
| Citations | None | Source: filename → heading path in every answer |
| Low confidence | Hallucination | Explicit disclosure + general knowledge fallback |
| Progress tracking | RAG guess | SQLite structured data (never inferred) |
| Ingestion speed | Always re-embeds | MD5 cache — skips unchanged files |

---

## Architecture

```
Browser (Next.js :3000)
        │
        ▼
FastAPI Backend (:8000)
        │
        ├── Progress question? ──→ SQLite (facts never inferred)
        │
        └── Knowledge question?
                │
                ├── 1. Query rewriting + reference resolution
                │        (conversation history → "explain that more" works)
                │
                ├── 2. Intent classification → topic routing
                │
                ├── 3. Parallel retrieval
                │        ├── Dense: mxbai-embed-large → ChromaDB (cosine)
                │        └── BM25:  keyword index (exact term matching)
                │
                ├── 4. RRF fusion (top-20)
                │
                ├── 5. bge-reranker-base cross-encoder (top-20 → top-5)
                │
                ├── 6. Confidence check
                │        ├── High → answer with [1][2] citations
                │        └── Low  → "not in notes — from general knowledge:"
                │
                └── 7. Ollama LLM (qwen2.5-coder:7b or qwen3:14b)
```

---

## Retrieval pipeline detail

```
User: "explain kafka rebalancing"
         │
         ▼
Query Rewriter
"Apache Kafka consumer group rebalancing partition assignment
 coordinator protocol offset commit"
         │
         ▼
Intent: system_design
         │
    ┌────┴────┐
    │         │
  Dense      BM25
  search     search
  (top-20)   (top-20)
    │         │
    └────┬────┘
         │
    RRF Fusion (top-20)
         │
    bge-reranker-base
    cross-encoder
         │
    Top-5 chunks
    (confidence: 0.82)
         │
    Prompt with citations:
    [1] kafka_notes.md → Kafka > Consumer Groups > Rebalancing
    [2] system_design_kb.md → Distributed Systems > Partition Assignment
         │
    qwen2.5-coder:7b
         │
    Answer with [1][2] inline citations
```

---

## Model selection

| RAM | Generation model | Command |
|-----|-----------------|---------|
| 16GB | qwen2.5-coder:7b (default) | `ollama pull qwen2.5-coder:7b` |
| 32GB | qwen3:14b (**recommended upgrade**) | `ollama pull qwen3:14b` |
| 48GB+ | qwen3:32b | `ollama pull qwen3:32b` |

Embedding (all configs): `mxbai-embed-large`
```bash
ollama pull mxbai-embed-large
```

To switch generation model — edit `.env`:
```
DEFAULT_MODEL=qwen3:14b
```
No code changes needed. Restart backend.

---

## First-time setup

### 1. Install Ollama
Download from https://ollama.com/download/mac → drag to Applications → launch.

### 2. Pull models
```bash
# Embedding model (required)
ollama pull mxbai-embed-large

# Generation model — choose based on your RAM
ollama pull qwen2.5-coder:7b    # 16GB RAM
# or
ollama pull qwen3:14b            # 32GB RAM (recommended)

# Verify
ollama list
```

### 3. Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
# Note: first run installs torch + sentence-transformers (~2GB)
# bge-reranker-base model (~270MB) downloads on first inference

mkdir -p data/{chroma,notes,sessions,stats}
cp .env.example .env
# Edit .env: set DEFAULT_MODEL based on your RAM

uvicorn app.main:app --reload --port 8000
```

Check: http://localhost:8000/docs

### 4. Frontend
```bash
cd frontend
npm install
npm run dev
```

Open: http://localhost:3000

---

## Adding your notes (knowledge base)

Drop files into `backend/data/notes/` organised by topic:

```
backend/data/notes/
├── dsa/                    ← LC solutions (.py .java), pattern notes (.md)
│   ├── two_sum.py
│   ├── sliding_window_patterns.md
│   └── ...
├── system_design/          ← design notes, case studies
│   ├── kafka_deep_dive.md
│   └── url_shortener_design.md
├── java/                   ← Spring notes, JVM internals
├── python/                 ← PySpark notes, pipeline code
├── aws/                    ← service comparisons, architecture notes
├── behavioral/             ← STAR stories (auto-detected, one story per chunk)
└── projects/               ← project descriptions, tech stack
```

**File naming matters for topic detection:**
- Files/folders containing `dsa`, `leetcode` → DSA topic
- `behavioral`, `star` → STAR story chunking
- `resume` → resume-specific chunking

---

## Ingestion commands

```bash
cd backend
source .venv/bin/activate

# First time or after adding many new files
python ingestion/ingest.py --source notes --clear

# Incremental update (skips unchanged files via MD5 cache)
python ingestion/ingest.py --source notes

# Force re-ingest all files even if unchanged
python ingestion/ingest.py --source notes --force

# Ingest a specific repo (e.g. your DE/DSA GitHub clone)
python ingestion/ingest.py --source repo --path /path/to/repo --topic dsa

# Ingest a single file
python ingestion/ingest.py --source file --path notes/kafka.md --topic system_design
```

Expected output:
```
✅  Ingested 312 semantic chunks
📊  ChromaDB collections:
   dsa                  → 218 chunks
   system_design        → 89 chunks
   java                 → 124 chunks
🧠  DSA Progress: 47 problems
    Patterns: ['Binary Search', 'Two Pointers', 'Graph DFS', ...]
    Missing:  ['Two Heaps', 'Monotonic Stack', 'Trie']
```

---

## Every session startup

```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Ollama starts automatically (lives in your menu bar).

---

## UI features

| Tab | What it does |
|-----|-------------|
| 💬 Chat | RAG-powered chat with citations and confidence disclosure |
| 🎯 Mock Interview | 6 personas (DSA/Design/Java/Python/AWS/Behavioral) — session persists across tab switches |
| 📄 Resume | Paste resume → extracted skills/projects used in interview questions |
| 📖 Story Bank | Add STAR stories → behavioral interviewer uses them automatically |
| 🔁 Revision | Generate Qs tab: LLM-powered senior questions. Due Today: spaced repetition queue |
| 📈 Progress | DSA patterns, topic mastery from KB, study recommendations |
| 🔍 Patterns | DSA pattern gap analysis vs senior-engineer benchmark |
| ⭐ STAR Scorer | Score behavioral answers with component-level feedback |

---

## How citations work

Every chat answer now includes source citations:

```
Two Pointers works by maintaining left and right indices... [1]

The key invariant: the window shrinks from the left when the
condition is violated, expands right otherwise... [2]

Sources:
[1] sliding_window_patterns.md → DSA > Two Pointers > Core Concept
[2] DSA_Knowledge_Base.md → Patterns > Two Pointers > Invariant
```

If your notes don't contain the answer:
```
This wasn't found in your notes — answering from general knowledge:
Apache Kafka uses a group coordinator to manage consumer group...
```

---

## Upgrading embedding model

If you were using `nomic-embed-text`, switching to `mxbai-embed-large` requires a full re-ingest:

```bash
# 1. Pull new model
ollama pull mxbai-embed-large

# 2. Update .env
EMBED_MODEL=mxbai-embed-large

# 3. Clear and re-ingest (old embeddings are incompatible)
python ingestion/ingest.py --source notes --clear
```

---

## Troubleshooting

**Reranker not loading:**
```bash
pip install sentence-transformers torch
# bge-reranker-base downloads ~270MB on first use
# Falls back gracefully to unranked results if unavailable
```

**Ollama not responding:**
```bash
ollama serve
```

**Port conflicts:**
```bash
uvicorn app.main:app --port 8001  # then update CORS_ORIGINS in .env
```

**Re-ingest not picking up changes:**
```bash
# Force re-ingest all files
python ingestion/ingest.py --source notes --force
```

**Low retrieval quality after switching embedding models:**
```bash
# Always clear when switching models — embeddings are model-specific
python ingestion/ingest.py --source notes --clear
```

---

## Project structure

```
backend/
├── app/
│   ├── api/routes/
│   │   ├── chat.py              # Routing, citations, confidence fallback
│   │   ├── interview.py         # Mock interview engine
│   │   ├── progress.py          # DSA/topic progress from SQLite
│   │   ├── analysis.py          # STAR scoring, revision questions
│   │   ├── memory.py            # ChromaDB endpoints
│   │   └── models.py            # Model list/health
│   ├── services/
│   │   ├── retrieval_service.py # Full pipeline: rewrite→classify→hybrid→rerank→cite
│   │   ├── llm_service.py       # Ollama wrapper, 8 interview personas
│   │   ├── memory_service.py    # ChromaDB with rich metadata
│   │   ├── progress_service.py  # Structured progress intelligence
│   │   ├── interview_service.py # Interview flow + resume extraction
│   │   ├── analysis_service.py  # Revision questions + STAR scoring
│   │   └── session_summary_service.py  # Long-term memory
│   ├── repositories/
│   │   ├── progress_repository.py      # SQLite: problems, mastery, weaknesses
│   │   ├── interview_repository.py     # SQLite: sessions, resume, stories, revision
│   │   ├── stats_repository.py         # SQLite: STAR scores, activity
│   │   └── session_repository.py       # JSON: chat sessions
│   ├── models/                  # Pydantic schemas
│   └── core/                    # Config, logging
├── ingestion/
│   ├── ingest.py                # Main ingestion script (semantic + cached)
│   ├── semantic_chunker.py      # Markdown-aware chunking
│   ├── ingestion_cache.py       # MD5 hash cache (skip unchanged files)
│   └── knowledge_base_parser.py # KB mastery entry extractor
└── data/                        # Local storage (gitignored)
    ├── chroma/                  # ChromaDB vector store
    ├── notes/                   # Your knowledge base (drop files here)
    ├── sessions/                # Chat sessions as JSON
    ├── stats/                   # STAR scores, activity logs
    ├── progress.db              # SQLite progress database
    └── ingestion_cache.json     # File hash cache
```