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

# ---------------------------------------------------------------------------
# Chrome remote debugging setup for agent scraping (bypasses Cloudflare)
# ---------------------------------------------------------------------------
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
AGENT_CHROME_PID=""
AGENT_CHROME_TMP=""

if curl -s --max-time 1 http://localhost:9222/json/version >/dev/null 2>&1; then
  # Chrome is already running with remote debugging — use it directly
  echo "✅ Chrome already running with remote debugging on port 9222 — agent will connect to it."
elif [ -f "$CHROME_BIN" ]; then
  # If Chrome is running WITHOUT remote debugging, quit it so we can relaunch with the flag
  if pgrep -x "Google Chrome" >/dev/null 2>&1; then
    echo "Quitting existing Chrome so it can relaunch with remote debugging..."
    pkill -x "Google Chrome" 2>/dev/null || true
    sleep 2
  fi

  CHROME_PROFILE="${CHROME_PROFILE_PATH:-$HOME/Library/Application Support/Google/Chrome}"
  echo "Launching Chrome with remote debugging (your real profile)..."
  echo ""
  echo "👉 In the Chrome window that opens:"
  echo "   1. Log in to Upwork if prompted"
  echo "   2. Solve any CAPTCHA / 'I am not a robot' check"
  echo "   The agent will connect automatically once Upwork loads."
  echo ""

  "$CHROME_BIN" \
    --remote-debugging-port=9222 \
    --user-data-dir="$CHROME_PROFILE" \
    --disable-blink-features=AutomationControlled \
    --no-first-run \
    --no-default-browser-check \
    "https://www.upwork.com" \
    2>/dev/null &
  AGENT_CHROME_PID=$!
  sleep 3
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
echo "Backend PID:      $BACKEND_PID"
echo "Frontend PID:     $FRONTEND_PID"
[ -n "$AGENT_CHROME_PID" ] && echo "Agent Chrome PID: $AGENT_CHROME_PID"
echo ""
echo "Open http://localhost:5173"
echo "Press Ctrl+C to stop all servers."

cleanup() {
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  [ -n "$AGENT_CHROME_PID" ] && kill "$AGENT_CHROME_PID" 2>/dev/null || true
  [ -n "$AGENT_CHROME_TMP" ] && rm -rf "$AGENT_CHROME_TMP" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM
wait
