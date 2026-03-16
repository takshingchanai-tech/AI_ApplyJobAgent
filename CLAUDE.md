# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UpworkJobApplyAgent is an AI agent that automates Upwork job applications with a human-in-the-loop (HITL) review step. It uses a **Manager Agent** (ReAct loop powered by LLM tool calling) that orchestrates three sub-agents: ScraperAgent (headless browser), JobScorerAgent (optional fit scoring), and CoverLetterAgent (LLM text + PDF). All data lives in SQLite. UI: React 18 + TypeScript + Vite + Zustand. Backend: Python FastAPI + SSE + browser-use.

## Development Instructions

After building or adding new features, always run tests and check logs until every new function and feature works properly.

## Runtime

Run Claude Code with:
```
claude --dangerously-skip-permissions
```

## Stack

- **Backend**: Python 3.9+, FastAPI, SQLite (WAL), browser-use, reportlab, openai SDK
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

## Agent Architecture

```
backend/agents/
├── manager.py          # ManagerAgent — LLM ReAct loop (tool calling), entry point: run_manager_agent()
├── scraper.py          # ScraperAgent — browser-use headless scraping, falls back to mock data
├── cover_letter_agent.py  # CoverLetterAgent — LLM text + PDF, 3x retry with backoff
├── scorer.py           # JobScorerAgent — optional LLM fit scoring (enable_job_scoring setting)
└── types.py            # Shared Pydantic contracts: ScraperResult, ScoredJob, CoverLetterResult, AgentState
```

### Manager ReAct loop
The manager calls `self._llm.chat.completions.create()` with 4 tools and `tool_choice="auto"`. The LLM reasons through a `user_context` message (keywords, search URL, filters) and calls tools in order: `scrape_jobs → score_and_filter_jobs → generate_cover_letters → finish`. Each tool result is appended to the message history so the LLM observes results before deciding the next action.

### New SSE events
- `react_thinking` — LLM's reasoning text before each tool call
- `phase_changed` — emitted when the manager dispatches a tool

## Notes

- Mock jobs returned if `browser-use` is not installed or fails (useful for UI testing)
- Chrome profile path lets the agent reuse existing Upwork login cookies
- `backend/agent.py` is kept but unused — replaced by `backend/agents/manager.py`
- Sibling projects for reference: `Agent2_memorySubagent_Qwen_E2Mobile` (SSE/agent pattern), `Agent2_memorySubagent` (DB + frontend pattern)
