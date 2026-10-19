# PrepAI — Personal Knowledge OS

> **Local-first AI learning and knowledge workspace built with production RAG engineering.**
> Runs entirely on your machine. Zero cloud. Zero API costs. Complete data privacy.

---

## Why this exists

Built to turn scattered notes, project context, and research into a searchable personal knowledge base that feels like an expert assistant working directly from your own material.

Every architectural choice here — hybrid retrieval, reranking, semantic chunking, confidence fallback — was made to solve a real problem, not to add complexity.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser  (Next.js :3000)                  │
│  Chat │ Notes │ Projects │ Research │ Revision │ Progress │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Backend  (:8000)                        │
│  ObservabilityMiddleware  →  trace_id + latency per request  │
│                                                              │
│   /api/chat      /api/knowledge    /api/analysis             │
│   /api/progress  /api/memory       /api/models               │
└──────┬────────────────────────────────────┬─────────────────┘
       │                                    │
       ▼                                    ▼
┌──────────────┐                  ┌──────────────────────────┐
│   SQLite DB  │                  │   Retrieval Pipeline      │
│              │                  │                           │
│ notes        │◄── progress Qs   │  1. Query Rewriting       │
│ projects     │    (facts, never │     + ref resolution      │
│ sessions     │     inferred)    │     ("explain that" →     │
│ topics       │                  │      previous topic)      │
│ concepts     │                  │                           │
│ stats        │                  │  2. Intent Classification │
└──────────────┘                  │     → topic routing       │
                                  │                           │
                                  │  3. Parallel search       │
                                  │   ┌─────────┬──────────┐  │
                                  │   │  Dense  │  BM25    │  │
                                  │   │  embed  │  keyword │  │
                                  │   │  top-20 │  top-20  │  │
                                  │   └────┬────┴────┬─────┘  │
                                  │        │ RRF     │         │
                                  │        ▼ fusion  ▼         │
                                  │     top-20 fused           │
                                  │                           │
                                  │  4. bge-reranker-base     │
                                  │     cross-encoder (MPS)   │
                                  │     top-20 → top-5        │
                                  │                           │
                                  │  5. Confidence check      │
                                  │   ≥0.35 → cited answer    │
                                  │   <0.35 → "not in notes"  │
                                  └──────────┬────────────────┘
                                             │
                                             ▼
                                  ┌──────────────────────────┐
                                  │  ChromaDB  (cosine)       │
                                  │  mxbai-embed-large        │
                                  │  Semantic chunks with     │
                                  │  heading_path, chunk_id,  │
                                  │  difficulty, chunk_type   │
                                  └──────────────────────────┘
                                             │
                                             ▼
                                  ┌──────────────────────────┐
                                  │  Ollama LLM              │
                                  │  qwen2.5-coder:7b (16GB) │
                                  │  qwen3:14b       (32GB)  │
                                  │  8 assistant personas    │
                                  │  num_predict=8192        │
                                  └──────────────────────────┘
```

---

## What makes this production-grade

| Problem | Naive approach | This project |
|---|---|---|
| Generic answers | Fixed 600-char chunks mix topics | Semantic markdown chunking — one concept per chunk |
| "Explain that more" breaks | No context | Query rewriting resolves references via conversation history |
| Dense retrieval misses exact terms | Embeddings only | Hybrid BM25 + dense with RRF fusion |
| Top-5 has irrelevant chunks | Cosine score only | bge-reranker-base cross-encoder on Apple Silicon MPS |
| Hallucination on unknown topics | Confident wrong answer | Confidence threshold → explicit "not in notes" disclosure |
| No source attribution | Black-box answers | Inline [1][2] citations with file → heading path |
| Re-embeds unchanged files | Slow re-ingestion | MD5 hash cache — skips unchanged files |
| Can't verify retrieval quality | No metrics | Evaluation harness: hit rate, MRR, context precision, latency |
| No production visibility | No logging | Per-request trace_id + latency, per-step timing |

---

## Retrieval pipeline in detail

```
User: "distributed tracing tail latency"
                │
                ▼
    ┌─────────────────────┐
    │   Query Rewriting   │  → "distributed tracing tail latency
    │ (short/ref queries) │     service dependency graph sampling
    └─────────────────────┘     observability bottleneck"
                │
                ▼
    ┌─────────────────────┐
    │ Intent Classification│  → topic: architecture
    └─────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
  Dense search        BM25 search
  mxbai-embed-large   keyword index
  ChromaDB top-20     in-memory top-20
        │                │
        └───────┬────────┘
                ▼
        RRF Fusion (k=60)
        top-20 by combined rank
                │
                ▼
    bge-reranker-base (MPS)
    cross-encoder scores each
    (query, chunk) pair
    top-20 → top-5
                │
                ▼
    Confidence = 0.82 ✓
                │
                ▼
    Context with citations:
    [1] observability_notes.md → Systems > Tracing > Tail Latency
    [2] architecture_kb.md → Distributed Systems > Sampling
                │
                ▼
    qwen2.5-coder:7b / qwen3:14b
                │
                ▼
    Answer with inline [1][2] citations
```

---

## Semantic chunking

**Before** (fixed 600-char): One chunk might contain architecture notes, observability details, and deployment guidance mixed together. The model retrieves 5 mixed chunks and produces a generic blend.

**After** (semantic): Each markdown `##` header becomes its own chunk with full lineage:

```
chunk: "## Rebalancing"
heading_path: "Systems > Distributed Data > Rebalancing"
topic: architecture
difficulty: medium
chunk_type: text
source: distributed_systems_notes.md
```

The model now gets 5 focused chunks on exactly the topic asked.

---

## Model selection

| RAM | Generation model | Quality |
|-----|-----------------|---------|
| 16 GB | `qwen2.5-coder:7b` (default) | Good — fast, solid coding |
| 32 GB | `qwen3:14b` (**recommended**) | Significantly better reasoning |
| 48 GB+ | `qwen3:32b` | Best local quality available |

Embedding: `mxbai-embed-large` (all configs)
- NDCG@10: 54.39 vs nomic-embed-text's 53.20 on MTEB retrieval
- Better on technical English, same Ollama interface

---

## First-time setup

### 1. Install Ollama
Download from https://ollama.com/download/mac

### 2. Pull models
```bash
ollama pull mxbai-embed-large       # embedding (required)
ollama pull qwen2.5-coder:7b        # 16GB RAM
# or
ollama pull qwen3:14b               # 32GB RAM (recommended upgrade)
```

### 3. Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
# Installs torch + sentence-transformers (~2GB first time)
# bge-reranker-base (~270MB) downloads on first inference request

mkdir -p data/{chroma,notes,sessions,stats}
cp .env.example .env
# Edit .env: set DEFAULT_MODEL based on your RAM

uvicorn app.main:app --reload --port 8000
```

### 4. Frontend
```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000

---

## Drop your notes here

```
backend/data/notes/
├── engineering/
│   ├── system_design.md          # Architecture notes — semantic chunked
│   ├── observability.md
│   └── api_patterns.md
├── research/
│   ├── retrieval_ranking.md       # Each ## header = one chunk
│   └── machine_learning.md
├── python/
│   └── async_patterns.md
├── java/
│   └── concurrency_notes.md
├── aws/
│   └── service_guide.md
├── projects/
│   └── product_context.md
└── personal/
    └── learning_notes.md
```

---

## Ingestion commands

```bash
cd backend && source .venv/bin/activate

# First time — clear old fixed-size chunks, re-ingest with semantic chunker
python ingestion/ingest.py --source notes --clear

# Incremental — skips unchanged files (MD5 cache)
python ingestion/ingest.py --source notes

# Force re-ingest all files even if unchanged
python ingestion/ingest.py --source notes --force

# Single file
python ingestion/ingest.py --source file --path notes/system_design.md --topic architecture

# External repo (e.g. your code or research notes)
python ingestion/ingest.py --source repo --path ~/code/notes --topic research
```

Expected output:
```
✅  Ingested 847 semantic chunks
📊  ChromaDB collections:
   engineering          → 312 chunks
   research             → 89 chunks
   python               → 124 chunks
   java                 → 98 chunks
   aws                  → 71 chunks
   personal             → 43 chunks
🧠  Knowledge coverage:
    Topics: ['system design', 'observability', 'retrieval', 'ML', 'Python']
    Missing: ['distributed systems', 'message queues', 'deployment']
```

---

## Run the evaluation harness

After ingestion, verify retrieval quality:

```bash
python -m app.services.evaluation
```

Output:
```
=======================================================
  PrepAI RAG Evaluation Report
=======================================================
  Queries evaluated : 15
  Hit Rate @5       : 86.7%
  MRR               : 0.712
  Context Precision : 73.3%
  Avg Latency       : 284 ms
  P95 Latency       : 412 ms
=======================================================

  By topic:
    aws                  hit=100%  (2 queries)
    engineering         hit=100%  (1 queries)
    java                 hit=100%  (2 queries)
    personal             hit=100%  (1 queries)
    python               hit=100%  (2 queries)
    research             hit=67%   (3 queries)
```

Or via API: `POST /api/analysis/evaluate`

---

## Every session

```bash
# Terminal 1
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Ollama runs in your menu bar automatically.

---

## UI features

| Tab | What it does |
|-----|-------------|
| 💬 Chat | Hybrid RAG with inline citations `[1][2]` and confidence fallback disclosure |
| 📝 Notes | Organize markdown knowledge and semantic search across your library |
| 📁 Projects | Attach project docs, context, and architecture notes to answer grounded questions |
| 🧠 Research | Ask questions using your local corpus with citations and topic routing |
| 🔁 Revision | Generate follow-up questions from your knowledge base and track learning progress |
| 📈 Progress | Topic mastery from your KB, daily study recommendations, and coverage gaps |
| 🔍 Knowledge Graph | Connect related concepts and understand topic overlap across sources |
| ⭐ Quality | Confidence tracking, retrieval metrics, and source-backed answers |

---

## Project structure

```
backend/
├── app/
│   ├── api/routes/
│   │   ├── chat.py              # Conversation routing + citations + fallback
│   │   ├── interview.py         # Mock interview engine + resume + stories
│   │   ├── analysis.py          # STAR scoring + revision + eval harness
│   │   ├── progress.py          # DSA/mastery progress from SQLite
│   │   ├── memory.py            # ChromaDB endpoints
│   │   └── models.py            # Ollama model list
│   ├── services/
│   │   ├── retrieval_service.py # Full pipeline: rewrite→classify→hybrid→rerank→cite
│   │   ├── llm_service.py       # Ollama wrapper + 8 interview personas
│   │   ├── memory_service.py    # ChromaDB with rich metadata
│   │   ├── interview_service.py # Interview flow + resume extraction
│   │   ├── analysis_service.py  # Revision Qs + STAR scoring
│   │   ├── progress_service.py  # Structured progress intelligence
│   │   ├── session_summary_service.py  # Long-term memory
│   │   └── evaluation.py        # RAG eval: hit rate, MRR, precision, latency
│   ├── repositories/
│   │   ├── progress_repository.py
│   │   ├── interview_repository.py     # sessions, resume, stories, revision
│   │   ├── stats_repository.py
│   │   └── session_repository.py
│   ├── models/                  # Pydantic schemas
│   └── core/
│       ├── config.py
│       ├── logging.py
│       └── observability.py     # Per-request trace_id + latency logging
├── ingestion/
│   ├── ingest.py                # Main script — semantic + cached
│   ├── semantic_chunker.py      # Markdown-aware chunking
│   ├── ingestion_cache.py       # MD5 cache (skip unchanged files)
│   └── knowledge_base_parser.py
└── data/                        # All local, gitignored
    ├── chroma/                  # Vector store
    ├── notes/                   # Your KB (drop files here)
    ├── sessions/                # Chat history as JSON
    ├── progress.db              # SQLite
    ├── eval_results.json        # Latest eval run
    └── ingestion_cache.json     # File hash cache
```

---

## Troubleshooting

**Reranker not loading:**
```bash
pip install sentence-transformers torch
# Falls back gracefully — answers still work, just not reranked
```

**Re-ingest not picking up new files:**
```bash
python ingestion/ingest.py --source notes --force
```

**Switched embedding model (e.g. nomic → mxbai):**
```bash
# Must clear — old embeddings are incompatible with new model
python ingestion/ingest.py --source notes --clear
```

**Low eval hit rate on a topic:**
```
→ Add more notes for that topic to data/notes/<topic>/
→ Re-run: python ingestion/ingest.py --source notes
→ Re-run eval to confirm improvement
```

---

## What this project is not

PrepAI is not a replacement for your own notes or a cloud AI service. It is a local-first knowledge companion that helps you search, reason over, and revisit your own material with citations and traceable answers.

---
