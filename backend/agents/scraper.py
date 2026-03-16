"""
ScraperAgent — all browser-use logic, isolated from the manager.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote_plus

from agents.types import ScraperResult

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_id_from_url(url: str) -> str:
    """Extract Upwork job ID from URL (e.g. ~01234567890abcdef)."""
    match = re.search(r'(~[0-9a-f]{16,})', url)
    return match.group(1) if match else ""


def _extract_jobs_from_text(text: str) -> list:
    """Try multiple strategies to extract a jobs list from LLM output."""
    if not text:
        return []

    # Strategy 1: strip markdown fences, then parse whole text as JSON
    clean = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`').strip()
    try:
        data = json.loads(clean)
        if isinstance(data, dict) and "jobs" in data:
            return data.get("jobs", [])
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: grab outermost { ... } block
    start = clean.find('{')
    end = clean.rfind('}')
    if start != -1 and end > start:
        try:
            data = json.loads(clean[start:end + 1])
            if isinstance(data, dict) and "jobs" in data:
                return data.get("jobs", [])
        except json.JSONDecodeError:
            pass

    # Strategy 3: grab outermost [ ... ] array
    start = clean.find('[')
    end = clean.rfind(']')
    if start != -1 and end > start:
        try:
            data = json.loads(clean[start:end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return []


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


class ScraperAgent:
    def __init__(self, settings: dict, sse_queue: asyncio.Queue):
        self.settings = settings
        self.sse_queue = sse_queue

    async def _emit(self, event: dict):
        await self.sse_queue.put(event)

    async def run(self, keywords: list, max_jobs: int, search_url: str) -> ScraperResult:
        """
        Run browser-use to scrape Upwork jobs. Never raises — wraps all errors
        in ScraperResult.error. Falls back to mock data on ImportError.
        """
        await self._emit({"type": "log", "level": "info", "message": "Launching headless browser..."})

        try:
            from browser_use import Agent as BrowserAgent
            from browser_use.browser.profile import BrowserProfile
            from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

            model_name = self.settings.get("model", "gpt-4o-mini")
            openai_api_key = self.settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
            dashscope_api_key = self.settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", "")

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

            chrome_profile = self.settings.get("chrome_profile", "") or os.getenv("CHROME_PROFILE_PATH", "")
            profile_kwargs = {"headless": True}
            if chrome_profile:
                profile_kwargs["user_data_dir"] = chrome_profile

            browser_profile = BrowserProfile(**profile_kwargs)

            task = f"""Go to {search_url}

If you are redirected to a login page, sign-in wall, or CAPTCHA, return immediately:
{{"error": "login_required", "jobs": []}}

Wait up to 5 seconds for job listings to load. Scroll down once to reveal all visible jobs.

Find up to {max_jobs} job listings. For EACH job listing:
1. Click the job title link to open the full job detail page.
2. Wait up to 5 seconds for the page to load fully.
3. Extract these fields from the detail page:
   - title: the full job title
   - client_name: client or company name if visible, else empty string
   - budget: e.g. "$500", "$25/hr", "$500-$1,000" (the posted budget or rate)
   - job_type: "Fixed" or "Hourly"
   - experience: "Entry Level", "Intermediate", or "Expert"
   - description: the COMPLETE, untruncated job description text (do not summarise)
   - skills: list of skill/expertise tags shown on the page
   - job_url: the current full page URL
   - id: the job ID from the URL (e.g. ~01234567890abcdef)
4. Click the browser Back button to return to the search results page.
5. Proceed to the next job listing.

After processing all jobs, return ONLY valid JSON — no markdown fences, no explanation, no extra text:
{{
  "jobs": [
    {{
      "id": "~01234567890abcdef",
      "title": "Job Title",
      "client_name": "Client Name or empty string",
      "budget": "$500 or $25/hr",
      "job_type": "Fixed or Hourly",
      "experience": "Entry Level / Intermediate / Expert",
      "description": "Full job description text",
      "skills": ["skill1", "skill2"],
      "job_url": "https://www.upwork.com/jobs/..."
    }}
  ]
}}"""

            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser_profile=browser_profile,
            )

            history = await agent.run()

            result_text = history.final_result() or ""
            if not result_text:
                extracted = history.extracted_content()
                result_text = "\n".join(extracted) if extracted else ""

            logger.info(f"[scraper] Raw result (first 500 chars): {result_text[:500]}")
            await self._emit({"type": "log", "level": "info",
                              "message": f"Browser result received ({len(result_text)} chars)"})

            # Check for login wall
            if "login_required" in result_text:
                try:
                    data = json.loads(result_text)
                    if data.get("error") == "login_required":
                        return ScraperResult(success=False, jobs=[], login_required=True)
                except Exception:
                    pass

            jobs = _extract_jobs_from_text(result_text)

            if not jobs:
                await self._emit({"type": "log", "level": "warn",
                                  "message": f"Could not parse job listings. Raw: {result_text[:300]}"})

            return ScraperResult(success=True, jobs=jobs)

        except ImportError:
            await self._emit({"type": "log", "level": "warn",
                              "message": "browser-use not available, using mock data for testing"})
            jobs = _get_mock_jobs(keywords)
            return ScraperResult(success=True, jobs=jobs)

        except Exception as e:
            await self._emit({"type": "log", "level": "error",
                              "message": f"Browser agent error: {e}"})
            return ScraperResult(success=False, jobs=[], error=str(e))
