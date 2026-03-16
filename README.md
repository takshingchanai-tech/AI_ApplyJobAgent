# UpworkJobApplyAgent

A local Mac AI agent that automates Upwork job applications with a **human-in-the-loop review step** before submitting.

The agent scrapes Upwork in headless mode, generates personalised cover letters, then opens a headed browser so you can review and click Submit yourself.

---

## How It Works

```
Start Agent
    │
    ▼
Headless Chrome scrapes Upwork jobs matching your keywords
    │
    ▼
Deduplication check (already seen? skip)
    │
    ▼
LLM generates personalised cover letter + saves as PDF
    │
    ▼
Job status → "Ready" · macOS notification fires
    │
    ▼
You click [→ Open for Review]
    │
    ▼
Headed Chrome opens proposal page with cover letter pre-filled
    │
    ▼
You review, edit if needed, click Submit on Upwork
    │
    ▼
Back in the app → click [✓ Mark as Applied]
```

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLite (WAL mode) |
| Browser automation | `browser-use` (scraping, headless) + Playwright (HITL, headed) |
| LLM | GPT-4o-mini (OpenAI) or Qwen Max (DashScope) |
| PDF generation | ReportLab |
| Frontend | React 18, TypeScript, Vite, Zustand |
| Real-time updates | Server-Sent Events (SSE) |

---

## Project Structure

```
UpworkJobApplyAgent/
├── start.sh                        # One-command startup
├── .env                            # API keys + Chrome profile path
├── data/
│   ├── upwork_agent.db             # SQLite database
│   ├── attachments/                # resume.pdf, portfolio.pdf
│   └── cover_letters/              # Generated PDFs per job
├── backend/
│   ├── main.py                     # FastAPI app + all routes
│   ├── agent.py                    # Scraping loop + SSE events
│   ├── browser_submit.py           # Headed browser HITL review
│   ├── cover_letter.py             # LLM text gen + PDF
│   ├── notifications.py            # macOS notifications
│   ├── requirements.txt
│   ├── database/db.py              # SQLite WAL init + schema
│   └── services/
│       ├── jobs.py                 # Job CRUD
│       └── settings.py            # Settings CRUD
└── frontend/
    └── src/
        ├── components/
        │   ├── TopBar/             # Start/Stop button
        │   ├── Sidebar/            # Nav with badge counts
        │   ├── Activity/           # Real-time agent log
        │   ├── Jobs/               # Job cards + action buttons
        │   └── Settings/           # Settings form
        ├── hooks/
        │   ├── useAgent.ts         # SSE consumer
        │   └── useSettings.ts
        └── store/                  # Zustand stores
```

---

## Setup

### 1. Prerequisites

- macOS
- [Homebrew](https://brew.sh) with Python 3.12: `brew install python@3.12`
- Node.js 18+: `brew install node`

### 2. Clone & configure

```bash
git clone <repo-url>
cd UpworkJobApplyAgent
```

Edit `.env`:
```env
OPENAI_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...         # Only needed if using Qwen
CHROME_PROFILE_PATH=             # Optional — see below
```

**Chrome Profile Path** (recommended): lets the agent reuse your existing Upwork login cookies so it doesn't need to log in on every run.

```
# Example path (use your actual profile):
/Users/yourname/Library/Application Support/Google/Chrome/Default
```

### 3. Run

```bash
./start.sh
```

- Backend starts on `http://localhost:8000`
- Frontend starts on `http://localhost:5173`
- Press `Ctrl+C` to stop both

> On first run, `start.sh` automatically creates the Python venv, installs all dependencies, and downloads Playwright's Chromium browser.

---

## Usage

### First-time setup (Settings)

Open `http://localhost:5173` → click **Settings**:

| Field | Description |
|-------|-------------|
| Model | `gpt-4o-mini` (faster/cheaper) or `qwen-max` |
| Keywords | Job search terms, e.g. `python developer, fastapi, automation` |
| Budget Min/Max | Filter by budget (0 = no limit) |
| Job Type | Any / Fixed / Hourly |
| Max Jobs Per Run | How many jobs to process per agent run (default 10) |
| Your Name | Used in cover letter generation |
| Skills | Your skills, used to personalise cover letters |
| Bio | Professional summary — the LLM uses this to write cover letters |
| Resume PDF | Upload your resume (attached to proposals) |
| Portfolio PDF | Upload your portfolio (attached to proposals) |
| Chrome Profile | Path to Chrome profile for Upwork login cookies |

### Running the agent

1. Click **Apply Jobs** in the top bar
2. Watch the **Activity** tab for live logs
3. macOS notification fires when a job is ready
4. Go to **Ready** tab → click **→ Open for Review**
5. Headed Chrome opens with cover letter pre-filled → review → submit
6. Back in app → click **✓ Mark as Applied**

### Job statuses

| Status | Meaning |
|--------|---------|
| `seen` | Found by agent, processing |
| `ready` | Cover letter generated, waiting for your review |
| `applying` | Browser open for HITL review |
| `applied` | You marked it as applied |
| `skipped` | Dismissed |

---

## API Reference

```
GET  /health                        Agent status + job counts
GET  /settings                      All settings
PUT  /settings                      Update settings

POST /agent/start                   Start scraping
POST /agent/stop                    Stop agent
GET  /agent/status                  Running state
GET  /agent/stream                  SSE event stream

GET  /jobs?status=ready             List jobs (filter by status)
GET  /jobs/counts                   Badge counts per status
GET  /jobs/{id}                     Single job
PATCH /jobs/{id}                    Update job fields
DELETE /jobs/{id}                   Skip job

POST /jobs/{id}/open-for-review     Launch headed browser
POST /jobs/{id}/mark-applied        Mark as applied

POST /attachments/resume            Upload resume PDF
POST /attachments/portfolio         Upload portfolio PDF
GET  /cover-letters/{id}            Download cover letter PDF
```

---

## Verify via SQLite

```bash
sqlite3 data/upwork_agent.db "SELECT title, status, applied_at FROM jobs;"
```

---

## Notes

- If `browser-use` fails to scrape (e.g. Upwork layout changed), the agent falls back to mock jobs — useful for testing the UI and cover letter generation flow without a live Upwork session.
- The agent uses your existing Chrome profile cookies for headless scraping, so you stay logged in to Upwork without re-authenticating.
- Cover letters are generated fresh for each job and saved as PDFs in `data/cover_letters/`.
- All data is stored locally — no cloud sync, no external database.
