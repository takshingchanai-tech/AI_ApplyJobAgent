"""
Upwork scraping agent using browser-use.
Puts SSE events into a global asyncio.Queue consumed by /agent/stream.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_scrape_agent(
    sse_queue: asyncio.Queue,
    settings: dict,
    run_id: str,
) -> None:
    """
    Main scraping loop. Searches Upwork for jobs matching keywords,
    deduplicates, generates cover letters, and saves to DB.
    """
    from services.jobs import job_exists, upsert_job, get_job_counts
    from cover_letter import generate_cover_letter_text, generate_pdf
    from notifications import send_notification

    async def emit(event: dict):
        await sse_queue.put(event)

    await emit({"type": "agent_started", "run_id": run_id, "timestamp": _now()})
    await emit({"type": "log", "level": "info", "message": "Agent starting up..."})

    keywords: list = settings.get("keywords", [])
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = [keywords]

    if not keywords:
        await emit({"type": "log", "level": "warn", "message": "No keywords configured. Add keywords in Settings."})
        await emit({"type": "agent_stopped", "reason": "done"})
        return

    max_jobs = int(settings.get("max_jobs_per_run", 10))
    budget_min = float(settings.get("budget_min", 0) or 0)
    budget_max = float(settings.get("budget_max", 0) or 0)
    job_type_filter = settings.get("job_type", "any")
    chrome_profile = settings.get("chrome_profile", "") or os.getenv("CHROME_PROFILE_PATH", "")

    await emit({"type": "log", "level": "info", "message": f"Searching for: {', '.join(keywords)} (max {max_jobs} jobs)"})

    jobs_found = 0
    jobs_ready = 0

    try:
        # Build search URL
        query = " ".join(keywords)
        search_url = f"https://www.upwork.com/nx/search/jobs/?q={query.replace(' ', '%20')}&sort=recency"

        await emit({"type": "log", "level": "info", "message": f"Launching headless browser..."})

        try:
            from browser_use import Agent as BrowserAgent
            from browser_use.browser.profile import BrowserProfile
            from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

            model_name = settings.get("model", "gpt-4o-mini")
            openai_api_key = settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
            dashscope_api_key = settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", "")

            if model_name == "qwen-max":
                llm = BUChatOpenAI(
                    model="qwen-max",
                    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                    api_key=dashscope_api_key,
                    temperature=0.1,
                )
            else:
                llm = BUChatOpenAI(
                    model=model_name,
                    api_key=openai_api_key,
                    temperature=0.1,
                )

            profile_kwargs = {"headless": True}
            if chrome_profile:
                profile_kwargs["user_data_dir"] = chrome_profile

            browser_profile = BrowserProfile(**profile_kwargs)

            task = f"""
Go to {search_url}

Find up to {max_jobs} job listings. For each job:
1. Extract: job title, client name (if shown), budget/rate, job type (Fixed/Hourly),
   experience level, full job description, required skills, and the job URL.
2. The job URL should be the full URL to that specific job posting.
3. Return ALL jobs as a JSON array with this structure:
{{
  "jobs": [
    {{
      "id": "extracted from URL (e.g. ~01234567890abcdef)",
      "title": "Job Title",
      "client_name": "Client Name or empty string",
      "budget": "$500 or $25/hr etc",
      "job_type": "Fixed or Hourly",
      "experience": "Entry Level / Intermediate / Expert",
      "description": "Full job description text",
      "skills": ["skill1", "skill2"],
      "job_url": "https://www.upwork.com/jobs/..."
    }}
  ]
}}

Return ONLY the JSON, no other text.
"""

            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser_profile=browser_profile,
            )

            history = await agent.run()

            # Extract result text from history
            result_text = history.final_result() or ""
            if not result_text:
                # Fall back to all extracted content joined together
                extracted = history.extracted_content()
                result_text = "\n".join(extracted) if extracted else ""

            logger.info(f"[agent] Raw result (first 500 chars): {result_text[:500]}")
            await emit({"type": "log", "level": "info", "message": f"Browser result received ({len(result_text)} chars)"})

            # Try to extract JSON from result
            scraped_jobs = []
            json_match = re.search(r'\{[\s\S]*?"jobs"[\s\S]*?\}(?=\s*$|\s*\Z)', result_text)
            if not json_match:
                json_match = re.search(r'\{[\s\S]*?"jobs"[\s\S]*\}', result_text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    scraped_jobs = data.get("jobs", [])
                except json.JSONDecodeError:
                    pass
            if not scraped_jobs:
                # Try extracting a JSON array directly
                arr_match = re.search(r'\[[\s\S]*\]', result_text)
                if arr_match:
                    try:
                        scraped_jobs = json.loads(arr_match.group())
                    except json.JSONDecodeError:
                        pass
            if not scraped_jobs:
                await emit({"type": "log", "level": "warn", "message": f"Could not parse job listings. Raw: {result_text[:300]}"})

        except ImportError:
            await emit({"type": "log", "level": "warn", "message": "browser-use not available, using mock data for testing"})
            scraped_jobs = _get_mock_jobs(keywords)
        except Exception as e:
            await emit({"type": "log", "level": "error", "message": f"Browser agent error: {e}"})
            scraped_jobs = []

        await emit({"type": "log", "level": "info", "message": f"Found {len(scraped_jobs)} job listings"})

        # Process each job
        for raw_job in scraped_jobs[:max_jobs]:
            job_id = raw_job.get("id") or _extract_id_from_url(raw_job.get("job_url", ""))
            if not job_id:
                job_id = str(uuid.uuid4())[:16]

            title = raw_job.get("title", "Untitled")
            jobs_found += 1

            # Dedup check
            if job_exists(job_id):
                await emit({"type": "job_skipped", "job_id": job_id, "reason": "already seen"})
                await emit({"type": "log", "level": "info", "message": f"Skipped (seen): {title}"})
                continue

            await emit({"type": "job_found", "job_id": job_id, "title": title, "budget": raw_job.get("budget", "")})
            await emit({"type": "log", "level": "info", "message": f"Processing: {title}"})

            # Save as 'seen' first
            job_data = {
                "id": job_id,
                "title": title,
                "client_name": raw_job.get("client_name", ""),
                "budget": raw_job.get("budget", ""),
                "job_type": raw_job.get("job_type", ""),
                "experience": raw_job.get("experience", ""),
                "description": raw_job.get("description", ""),
                "skills": raw_job.get("skills", []),
                "job_url": raw_job.get("job_url", ""),
                "status": "seen",
            }
            upsert_job(job_data)

            # Generate cover letter
            await emit({"type": "generating_cover_letter", "job_id": job_id, "title": title})
            await emit({"type": "log", "level": "info", "message": f"Generating cover letter for: {title}"})

            try:
                cover_text = await generate_cover_letter_text(job_data, settings)
                pdf_path = generate_pdf(job_id, cover_text)

                # Update job to 'ready'
                from services.jobs import update_job
                update_job(job_id, {
                    "status": "ready",
                    "cover_letter_text": cover_text,
                    "cover_letter_pdf": pdf_path,
                })

                jobs_ready += 1
                await emit({
                    "type": "job_ready",
                    "job_id": job_id,
                    "title": title,
                    "job_url": raw_job.get("job_url", ""),
                })
                await emit({"type": "log", "level": "info", "message": f"Ready: {title}"})

                # macOS notification
                send_notification(
                    "Upwork Job Ready",
                    title,
                    subtitle="Cover letter generated",
                )

            except Exception as e:
                await emit({"type": "error", "message": str(e), "job_id": job_id})
                await emit({"type": "log", "level": "error", "message": f"Cover letter failed for {title}: {e}"})

            # Emit updated counts
            counts = get_job_counts()
            await emit({"type": "counts_updated", "counts": counts})

            # Small delay to be respectful
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        await emit({"type": "agent_stopped", "reason": "cancelled"})
        return
    except Exception as e:
        logger.error(f"Agent error: {e}")
        await emit({"type": "error", "message": str(e)})
        await emit({"type": "agent_stopped", "reason": "error"})
        return

    await emit({"type": "done", "jobs_found": jobs_found, "jobs_ready": jobs_ready})
    await emit({"type": "agent_stopped", "reason": "done"})
    await emit({"type": "log", "level": "info", "message": f"Done. Found: {jobs_found}, Ready: {jobs_ready}"})


def _extract_id_from_url(url: str) -> str:
    """Extract Upwork job ID from URL (e.g. ~01234567890abcdef)."""
    match = re.search(r'(~[0-9a-f]{16,})', url)
    return match.group(1) if match else ""


def _get_mock_jobs(keywords: list) -> list:
    """Return mock jobs for testing when browser-use is unavailable."""
    return [
        {
            "id": "~mock001",
            "title": f"Python Developer for {keywords[0] if keywords else 'Web'} Project",
            "client_name": "Test Client",
            "budget": "$500 - $1,000",
            "job_type": "Fixed",
            "experience": "Intermediate",
            "description": "We need an experienced Python developer to build a web scraping tool. "
                           "The ideal candidate has experience with FastAPI, Playwright, and SQLite. "
                           "This is a short-term project with potential for ongoing work.",
            "skills": ["Python", "FastAPI", "Playwright", "SQLite"],
            "job_url": "https://www.upwork.com/jobs/~mock001",
        },
        {
            "id": "~mock002",
            "title": f"AI Agent Developer — {keywords[0] if keywords else 'Automation'}",
            "client_name": "Startup Co",
            "budget": "$30/hr",
            "job_type": "Hourly",
            "experience": "Expert",
            "description": "Looking for an AI agent developer to build automation workflows "
                           "using LLMs. Must have experience with LangChain, OpenAI API, and "
                           "browser automation. Remote work, flexible hours.",
            "skills": ["Python", "LangChain", "OpenAI", "LLM", "browser-use"],
            "job_url": "https://www.upwork.com/jobs/~mock002",
        },
    ]
