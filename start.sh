#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== UpworkJobApplyAgent ==="

# Start backend
cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment..."
  /opt/homebrew/bin/python3.12 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

# Install Playwright browser if not already present
if ! python -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__().chromium" 2>/dev/null; then
  echo "Installing Playwright Chromium..."
  playwright install chromium --quiet 2>/dev/null || true
fi

echo "Starting backend on :8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install
fi

echo "Starting frontend on :5173..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Open http://localhost:5173"
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM
wait
