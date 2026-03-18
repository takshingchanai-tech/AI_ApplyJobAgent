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

# Persistent profile dir — saves Upwork login/cookies between runs
AGENT_CHROME_PROFILE="$PROJECT_DIR/.chrome-agent-profile"

if curl -s --max-time 1 http://localhost:9222/json/version >/dev/null 2>&1; then
  # Chrome is already running with remote debugging — use it directly
  echo "✅ Chrome already running with remote debugging on port 9222 — agent will connect to it."
elif [ -f "$CHROME_BIN" ]; then
  # Use a persistent profile so Upwork login and cookies are saved between runs.
  # A dedicated dir avoids the singleton handoff issue when main Chrome is already open.
  mkdir -p "$AGENT_CHROME_PROFILE"

  echo "Launching agent Chrome with remote debugging..."
  echo ""
  echo "👉 In the Chrome window that opens:"
  echo "   - If it's your first run: log in to Upwork and solve any CAPTCHA."
  echo "   - On future runs your session will be remembered automatically."
  echo ""

  "$CHROME_BIN" \
    --remote-debugging-port=9222 \
    --user-data-dir="$AGENT_CHROME_PROFILE" \
    --disable-blink-features=AutomationControlled \
    --no-first-run \
    --no-default-browser-check \
    "https://www.upwork.com" \
    2>/dev/null &
  AGENT_CHROME_PID=$!

  # Wait until Chrome is actually ready on port 9222 (up to 15 seconds)
  echo "Waiting for Chrome to be ready on port 9222..."
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    sleep 1
    if curl -s --max-time 1 http://localhost:9222/json/version >/dev/null 2>&1; then
      echo "✅ Chrome ready on port 9222."
      break
    fi
  done
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
  exit 0
}
trap cleanup SIGINT SIGTERM
wait
