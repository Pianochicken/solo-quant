#!/bin/bash

# Function to kill background processes on exit
cleanup() {
    echo "Stopping servers..."
    kill $(jobs -p)
    exit
}

trap cleanup SIGINT

# 1. Start Backend (FastAPI)
echo "🚀 Starting FastAPI Backend (Port 8000)..."
source .venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(pwd)
uvicorn api.main:app --reload --port 8000 &

# Wait a moment for backend
sleep 2

# 2. Start Frontend (Next.js)
echo "⚛️ Starting Next.js Frontend (Port 3000)..."
cd web
npm run dev

# Keep script running to maintain background jobs
wait
