#!/bin/bash
# scripts/setup.sh — first-time setup for PrepAI

set -e

echo "🧠 PrepAI Setup"
echo "==============="

# Check Ollama
if ! command -v ollama &>/dev/null; then
  echo "❌ Ollama not found. Install from https://ollama.com/download/mac"
  exit 1
fi
echo "✅ Ollama found"

# Pull models
echo ""
echo "📦 Pulling models (this takes a few minutes)..."
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
echo "✅ Models ready"

# Backend
echo ""
echo "🐍 Setting up Python backend..."
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
mkdir -p data/{chroma,notes,sessions}
cp .env.example .env 2>/dev/null || true
echo "✅ Backend ready"

# Frontend
echo ""
echo "⚡ Installing frontend dependencies..."
cd ../frontend
npm install --silent
echo "✅ Frontend ready"

echo ""
echo "🚀 Setup complete!"
echo ""
echo "Start the backend:   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload"
echo "Start the frontend:  cd frontend && npm run dev"
echo "Then open:           http://localhost:3000"
echo ""
echo "Add your notes to:   backend/data/notes/"
echo "Then ingest:         python backend/ingestion/ingest.py --source notes"
