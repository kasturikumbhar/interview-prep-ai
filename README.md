# PrepAI — Personal Interview Preparation OS

> A local-first AI system that tracks your actual interview preparation progress — not a generic chatbot.

![Demo](docs/demo.gif)

---

## What makes this different

Most AI interview tools do semantic search and ask the LLM to guess your progress.

PrepAI has a **Progress Layer** — structured SQLite-backed tracking of every problem you've solved, every pattern covered, and every weakness identified across sessions. The LLM uses this as ground truth, not inference.

| Question | Generic RAG chatbot | PrepAI |
|---|---|---|
| "What patterns have I covered?" | LLM guesses from notes | Queries SQLite → returns exact count per pattern |
| "What should I study today?" | Semantic search + hallucination | Analyzes gaps, revision count, session history → ranked recommendations |
| "What are my weak areas?" | LLM infers from text | Aggregated from structured session analysis |

---

## Architecture

```
Browser (Next.js :3000)
        │
        ▼
FastAPI Backend (:8000)
   │
   ├── Progress question? ──→ SQLite Progress DB
   │                          (problems, patterns, scores, weaknesses)
   │
   ├── Knowledge question? ──→ ChromaDB (RAG)
   │                           (your notes, solutions, design docs)
   │
   └── Both ──→ Ollama (local LLM)
                 qwen2.5-coder:7b  — coding/DSA/AWS
                 nomic-embed-text  — embeddings
```

**Everything runs locally. No data leaves your machine.**

---

## Features

### Progress Intelligence
- Tracks solved problems, patterns, difficulty from your actual solution files
- Detects pattern gaps against a senior-engineer benchmark (19 core patterns)
- Revision queue ranked by priority (low revision count + high difficulty = top priority)
- "What to study today" — structured recommendations, no LLM guessing

### Long-term Memory
- Every N messages: auto-summarizes session into structured data (topics covered, weaknesses, next actions)
- Summaries injected into future prompts — the assistant remembers your history

### Interview Modes
- 6 specialized interview personas: DSA, System Design, Java, Python, AWS, Behavioral
- STAR answer scorer with component-level feedback (Situation/Task/Action/Result)
- Session weakness analysis

### RAG Pipeline
- ChromaDB vector store with per-topic collections
- Ingests markdown notes, Python/Java solution files, design docs
- Auto-detects topic from directory structure

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React 19, inline styles (zero dependencies) |
| Backend | FastAPI, Python 3.9+ |
| LLM | Ollama (local) — qwen2.5-coder:7b |
| Embeddings | nomic-embed-text (local) |
| Vector DB | ChromaDB |
| Progress DB | SQLite (via Python stdlib) |
| Session storage | JSON files |

---

## Running locally

### Prerequisites
- macOS / Linux
- Python 3.9+
- Node.js 20+
- [Ollama](https://ollama.com/download)

### 1. Pull models

```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p data/{chroma,notes,sessions,stats}
cp .env.example .env

uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### 4. Ingest your notes

Drop your markdown notes, DSA solutions, and design docs into `backend/data/notes/`:

```
backend/data/notes/
  dsa/          ← Python/Java LC solutions (auto-extracts pattern + difficulty)
  system_design/
  java/
  python/
  aws/
  behavioral/   ← STAR stories
```

Then run:

```bash
cd backend
python ingestion/ingest.py --source notes
```

Output:
```
→ Progress DB: Two_Sum | Two Pointers | Easy
→ Progress DB: Merge_Intervals | Merge Intervals | Medium
→ Progress DB: Word_Search | Backtracking | Hard

✅ Ingested 312 chunks into ChromaDB

🧠 Progress DB:
   Problems tracked: 47
   Patterns found:   ['Two Pointers', 'Binary Search', 'Tree DFS', ...]
   Missing patterns: ['Two Heaps', 'Monotonic Stack', 'Trie', ...]
```

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/routes/
│   │   │   ├── chat.py          # Routes progress Qs → DB, knowledge Qs → RAG
│   │   │   ├── progress.py      # /progress/* endpoints
│   │   │   ├── memory.py        # /memory/* RAG endpoints
│   │   │   └── analysis.py      # STAR scoring, weakness analysis
│   │   ├── services/
│   │   │   ├── llm_service.py         # Ollama wrapper, 6 interview personas
│   │   │   ├── memory_service.py      # ChromaDB RAG pipeline
│   │   │   ├── progress_service.py    # Structured progress intelligence
│   │   │   ├── session_summary_service.py  # Long-term memory
│   │   │   └── analysis_service.py    # LLM-powered analysis
│   │   ├── repositories/
│   │   │   ├── progress_repository.py  # SQLite — problems, patterns, scores
│   │   │   └── session_repository.py   # JSON session persistence
│   │   └── models/              # Pydantic schemas
│   ├── ingestion/
│   │   └── ingest.py            # Chunk + embed + extract metadata
│   └── data/                    # Local storage (gitignored)
│       ├── chroma/              # ChromaDB vector store
│       ├── notes/               # Drop your notes here
│       ├── sessions/            # Chat sessions as JSON
│       └── progress.db          # SQLite progress database
└── frontend/
    └── src/app/
        └── page.tsx             # Single-file UI, 5 views
```

---

## API

Backend exposes a self-documented API at http://localhost:8000/docs

Key endpoints:

```
POST /api/chat/                    Chat with context routing
GET  /api/progress/dsa             Full DSA progress from DB
GET  /api/progress/gaps            Pattern gap analysis
GET  /api/progress/today           What to study today (structured)
GET  /api/progress/revision        Revision queue ranked by priority
POST /api/progress/problem         Manually log a solved problem
POST /api/memory/ingest            Add content to RAG
GET  /api/memory/stats             ChromaDB collection counts
POST /api/analysis/star            Score a STAR behavioral answer
POST /api/analysis/weakness        Analyze session weaknesses
```

---

## Privacy

- All inference runs on your hardware via Ollama
- All data stored in `backend/data/` on your machine
- No telemetry, no cloud sync, no API keys required
- ChromaDB configured with `anonymized_telemetry=False`

---

## Roadmap

- [ ] Spaced repetition scheduler for revision queue
- [ ] PDF export of session summaries
- [ ] Flashcard mode from ingested notes
- [ ] Multi-language support (Java solution metadata extraction)
- [ ] Weekly progress email digest (local SMTP)

---

## Built with

- [Ollama](https://ollama.com) — local model serving
- [ChromaDB](https://www.trychroma.com) — vector storage
- [FastAPI](https://fastapi.tiangolo.com) — async Python backend
- [Next.js](https://nextjs.org) — React frontend
