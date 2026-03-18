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
  echo ""
  echo "⚠️  For best results (bypass Cloudflare), launch Chrome with remote debugging BEFORE running this script:"
  echo "   open -a 'Google Chrome' --args --remote-debugging-port=9222 --disable-blink-features=AutomationControlled"
  echo ""
  echo "Launching agent Chrome now (may hit Cloudflare challenge)..."
  CHROME_PROFILE_SRC="${CHROME_PROFILE_PATH:-$HOME/Library/Application Support/Google/Chrome/Default}"
  AGENT_CHROME_TMP=$(mktemp -d)
  mkdir -p "$AGENT_CHROME_TMP/Default"
  for f in "Cookies" "Preferences" "Network Persistent State" "Visited Links"; do
    cp "$CHROME_PROFILE_SRC/$f" "$AGENT_CHROME_TMP/Default/" 2>/dev/null || true
  done
  cp -r "$CHROME_PROFILE_SRC/Local Storage" "$AGENT_CHROME_TMP/Default/" 2>/dev/null || true
  cp "$(dirname "$CHROME_PROFILE_SRC")/Local State" "$AGENT_CHROME_TMP/" 2>/dev/null || true

  "$CHROME_BIN" \
    --remote-debugging-port=9222 \
    --user-data-dir="$AGENT_CHROME_TMP" \
    --disable-blink-features=AutomationControlled \
    --no-first-run \
    --no-default-browser-check \
    --disable-extensions \
    --window-position=-32000,-32000 \
    2>/dev/null &
  AGENT_CHROME_PID=$!
  sleep 2
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
