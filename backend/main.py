"""
FastAPI backend for UpworkJobApplyAgent.
All routes, lifespan, and SSE queue management.
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

sse_queue: asyncio.Queue = asyncio.Queue()
_agent_task: Optional[asyncio.Task] = None
_run_id: Optional[str] = None
_started_at: Optional[str] = None

ATTACHMENTS_DIR = Path(__file__).parent.parent / "data" / "attachments"
COVER_LETTERS_DIR = Path(__file__).parent.parent / "data" / "cover_letters"
PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    from database.db import get_db
    get_db()
    logger.info("UpworkJobApplyAgent initialized.")
    yield
    logger.info("UpworkJobApplyAgent shutting down.")


app = FastAPI(title="UpworkJobApplyAgent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JobUpdate(BaseModel):
    status: Optional[str] = None
    cover_letter_text: Optional[str] = None
    title: Optional[str] = None
    budget: Optional[str] = None

class SettingsUpdate(BaseModel):
    model: Optional[str] = None
    keywords: Optional[list] = None
    budget_min: Optional[Union[str, int, float]] = None
    budget_max: Optional[Union[str, int, float]] = None
    job_type: Optional[str] = None
    experience: Optional[str] = None
    max_jobs_per_run: Optional[Union[str, int]] = None
    chrome_profile: Optional[str] = None
    freelancer_name: Optional[str] = None
    freelancer_skills: Optional[list] = None
    freelancer_bio: Optional[str] = None
    resume_path: Optional[str] = None
    portfolio_path: Optional[str] = None
    openai_api_key: Optional[str] = None
    dashscope_api_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    from services.jobs import get_job_counts
    counts = get_job_counts()
    return {
        "status": "ok",
        "agent_running": _agent_task is not None and not _agent_task.done(),
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@app.post("/agent/start")
async def agent_start():
    global _agent_task, _run_id, _started_at

    if _agent_task and not _agent_task.done():
        raise HTTPException(status_code=409, detail="Agent already running")

    from services.settings import get_all_settings
    settings = get_all_settings()

    # Inject env API keys if not set in DB
    if not settings.get("openai_api_key"):
        settings["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")
    if not settings.get("dashscope_api_key"):
        settings["dashscope_api_key"] = os.getenv("DASHSCOPE_API_KEY", "")

    _run_id = str(uuid.uuid4())[:8]
    _started_at = datetime.now(timezone.utc).isoformat()

    from agent import run_scrape_agent
    _agent_task = asyncio.create_task(
        run_scrape_agent(sse_queue, settings, _run_id)
    )

    return {"status": "started", "run_id": _run_id}


@app.post("/agent/stop")
async def agent_stop():
    global _agent_task
    if _agent_task and not _agent_task.done():
        _agent_task.cancel()
        return {"status": "stopping"}
    return {"status": "not_running"}


@app.get("/agent/status")
async def agent_status():
    running = _agent_task is not None and not _agent_task.done()
    return {
        "running": running,
        "run_id": _run_id if running else None,
        "started_at": _started_at if running else None,
    }


@app.get("/agent/stream")
async def agent_stream():
    """SSE stream — drains the global sse_queue."""

    async def event_generator():
        # Send initial ping
        yield "data: " + json.dumps({"type": "ping"}) + "\n\n"

        while True:
            try:
                # Drain queue with 15s timeout (keepalive ping)
                event = await asyncio.wait_for(sse_queue.get(), timeout=15.0)
                yield "data: " + json.dumps(event) + "\n\n"
            except asyncio.TimeoutError:
                yield "data: " + json.dumps({"type": "ping"}) + "\n\n"
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/jobs")
async def list_jobs(status: Optional[str] = None):
    from services.jobs import list_jobs as svc_list
    return svc_list(status)


@app.get("/jobs/counts")
async def job_counts():
    from services.jobs import get_job_counts
    return get_job_counts()


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    from services.jobs import get_job as svc_get
    job = svc_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.patch("/jobs/{job_id}")
async def patch_job(job_id: str, body: JobUpdate):
    from services.jobs import update_job
    updates = body.model_dump(exclude_none=True)
    result = update_job(job_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.delete("/jobs/{job_id}", status_code=204)
async def skip_job(job_id: str):
    from services.jobs import delete_job
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")


@app.post("/jobs/{job_id}/open-for-review")
async def open_for_review(job_id: str):
    from services.jobs import get_job, update_job
    from services.settings import get_all_settings

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update status to applying
    update_job(job_id, {"status": "applying"})

    settings = get_all_settings()
    if not settings.get("openai_api_key"):
        settings["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")

    # Launch browser in background (non-blocking for the API response)
    from browser_submit import open_for_review as browser_open
    asyncio.create_task(browser_open(job, settings))

    return {"status": "opening", "job_id": job_id}


@app.post("/jobs/{job_id}/mark-applied")
async def mark_applied(job_id: str):
    from services.jobs import update_job, get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from datetime import datetime, timezone
    result = update_job(job_id, {
        "status": "applied",
        "applied_at": datetime.now(timezone.utc).isoformat(),
    })
    return result


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

@app.post("/attachments/resume")
async def upload_resume(file: UploadFile = File(...)):
    path = ATTACHMENTS_DIR / "resume.pdf"
    content = await file.read()
    path.write_bytes(content)
    # Save path to settings
    from services.settings import update_settings
    update_settings({"resume_path": str(path)})
    return {"status": "ok", "path": str(path)}


@app.post("/attachments/portfolio")
async def upload_portfolio(file: UploadFile = File(...)):
    path = ATTACHMENTS_DIR / "portfolio.pdf"
    content = await file.read()
    path.write_bytes(content)
    from services.settings import update_settings
    update_settings({"portfolio_path": str(path)})
    return {"status": "ok", "path": str(path)}


@app.get("/cover-letters/{job_id}")
async def get_cover_letter(job_id: str):
    from services.jobs import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    pdf_path = job.get("cover_letter_pdf", "")
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No cover letter PDF")

    full_path = PROJECT_ROOT / pdf_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(str(full_path), media_type="application/pdf")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings")
async def get_settings():
    from services.settings import get_all_settings
    return get_all_settings()


@app.put("/settings")
async def put_settings(body: SettingsUpdate):
    from services.settings import update_settings
    updates = body.model_dump(exclude_none=True)
    return update_settings(updates)
