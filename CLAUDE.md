# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UpworkJobApplyAgent is an AI agent that automates Upwork job applications with a human-in-the-loop (HITL) review step. It scrapes Upwork using a **hybrid Playwright + LLM** approach (deterministic Playwright for navigation/extraction, LLM only for login-wall detection and field-level fallback), generates cover letters + PDFs, then opens a headed browser for the user to review and click Submit. All data lives in SQLite. UI: React 18 + TypeScript + Vite + Zustand. Backend: Python FastAPI + SSE.

## Development Instructions

After building or adding new features, always run tests and check logs until every new function and feature works properly.

## Runtime

Run Claude Code with:
```
claude --dangerously-skip-permissions
```

## Stack

- **Backend**: Python 3.9+, FastAPI, SQLite (WAL), Playwright (primary scraper), browser-use (fallback), reportlab, openai SDK
- **Frontend**: React 18 + TypeScript + Vite + Zustand
- **Models**: GPT-4o-mini (OpenAI) or Qwen Max (DashScope, OpenAI-compatible)

## Build & Run

```bash
# Full stack (backend :8000, frontend :5173)
./start.sh

# Backend only
cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

# Frontend only
cd frontend && npm run dev

# Frontend type check + build
cd frontend && npx tsc --noEmit && npm run build
```

## Post-install

```bash
cd backend && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Environment (.env)

```
OPENAI_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...
CHROME_PROFILE_PATH=/path/to/Chrome/profile   # optional
```

## Verify (SQLite)

```bash
sqlite3 data/upwork_agent.db "SELECT title, status, applied_at FROM jobs;"
```

## HITL Flow

1. Start Agent → agent scrapes Upwork (headless), generates cover letters, status = `ready`
2. User clicks "Open for Review" → headed browser opens job proposal page with cover letter pre-filled
3. User clicks Submit on Upwork → returns to app → clicks "Mark as Applied"

## Scraping Architecture

`agent.py` uses a three-tier fallback chain:
1. **Playwright** (primary) — deterministic selectors, no LLM tokens spent on navigation
2. **browser-use** (fallback) — LLM-driven agent if Playwright returns no results
3. **Mock data** (dev fallback) — if browser-use is not installed or fails

LLM is called inside Playwright only for: login-wall confirmation and per-field extraction when DOM selectors miss.

## Notes

- Chrome profile path lets the agent reuse existing Upwork login cookies
- Mock jobs returned if both scrapers fail (useful for UI testing)
- Sibling projects for reference: `Agent2_memorySubagent_Qwen_E2Mobile` (SSE/agent pattern), `Agent2_memorySubagent` (DB + frontend pattern)
