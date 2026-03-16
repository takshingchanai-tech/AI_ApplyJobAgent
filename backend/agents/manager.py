"""
ManagerAgent — true ReAct loop powered by LLM tool calling.

The LLM reasons about the current state and decides which sub-agent to
invoke next. Sub-agents are the "tools". The LLM is never rule-hard-coded
to a fixed sequence — it observes results and decides what to do.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote_plus

from openai import AsyncOpenAI

from agents.types import AgentState, ScoredJob

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 10   # safety cap — prevents infinite loops


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_budget_value(budget_str: str):
    if not budget_str:
        return None
    numbers = re.findall(r'[\d]+(?:\.\d+)?', budget_str.replace(',', ''))
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            pass
    return None


def _apply_filters(jobs: list, settings: dict) -> list:
    budget_min = float(settings.get("budget_min", 0) or 0)
    budget_max = float(settings.get("budget_max", 0) or 0)
    job_type_filter = (settings.get("job_type", "any") or "any").lower()
    experience_filter = (settings.get("experience", "any") or "any").lower()

    filtered = []
    for job in jobs:
        if budget_min > 0 or budget_max > 0:
            val = _parse_budget_value(job.get("budget", ""))
            if val is not None:
                if budget_min > 0 and val < budget_min:
                    continue
                if budget_max > 0 and val > budget_max:
                    continue

        if job_type_filter != "any":
            jt = (job.get("job_type", "") or "").lower()
            if job_type_filter == "fixed" and "fixed" not in jt:
                continue
            if job_type_filter == "hourly" and "hourly" not in jt:
                continue

        if experience_filter != "any":
            exp = (job.get("experience", "") or "").lower()
            exp_map = {"entry": ["entry"], "intermediate": ["intermediate"], "expert": ["expert"]}
            allowed = exp_map.get(experience_filter, [])
            if not any(a in exp for a in allowed):
                continue

        filtered.append(job)
    return filtered


def _extract_id_from_url(url: str) -> str:
    match = re.search(r'(~[0-9a-f]{16,})', url)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Tool definitions passed to the LLM
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scrape_jobs",
            "description": (
                "Launch the headless browser agent to scrape Upwork job listings "
                "matching the configured keywords. Returns a list of job summaries "
                "and indicates whether login is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search_url": {
                        "type": "string",
                        "description": "Full Upwork search URL including query params.",
                    },
                    "max_jobs": {
                        "type": "integer",
                        "description": "Maximum number of jobs to scrape.",
                    },
                },
                "required": ["search_url", "max_jobs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_and_filter_jobs",
            "description": (
                "Score scraped jobs for fit against the freelancer profile and filter "
                "out low-scoring ones. Returns the approved job IDs with scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Job IDs to score (must come from a previous scrape_jobs result).",
                    },
                    "score_threshold": {
                        "type": "number",
                        "description": "Minimum score 0.0–1.0 to approve a job. Default 0.6.",
                    },
                },
                "required": ["job_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cover_letters",
            "description": (
                "Generate cover letters (LLM text + PDF) for a list of approved jobs "
                "and save them as ready for review."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Approved job IDs to generate cover letters for.",
                    },
                },
                "required": ["job_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "End the agent run and emit a final summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": ["done", "login_required", "no_jobs", "no_matching_jobs", "error"],
                        "description": "Why the run is ending.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Human-readable summary of what happened this run.",
                    },
                },
                "required": ["reason", "summary"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a workflow manager agent for an Upwork job application system.
Your goal is to find relevant Upwork jobs and prepare cover letters for the freelancer to review.

You have four tools:
- scrape_jobs: launches a headless browser to scrape Upwork job listings
- score_and_filter_jobs: scores jobs against the freelancer profile and filters out poor fits
- generate_cover_letters: generates LLM cover letters + PDFs for approved jobs
- finish: ends the run

## Mandatory workflow order
You MUST follow this sequence every run — do not skip or reorder steps:
1. ALWAYS call scrape_jobs first using the search_url and max_jobs from the user message.
2. ALWAYS call score_and_filter_jobs next, passing the job IDs returned by scrape_jobs.
3. ALWAYS call generate_cover_letters next, passing the approved job IDs from score_and_filter_jobs.
4. ALWAYS call finish last with a summary of what happened.

## How to reason
Before every tool call, think out loud:
1. What did the last tool return? (observations)
2. What does that mean for the next step? (reasoning)
3. Which tool will you call and with what arguments? (decision)

## Decision guidelines — when to deviate from the workflow
- If scrape returns login_required=true → skip steps 2–3, call finish(reason="login_required")
- If scrape returns 0 jobs → retry scrape_jobs once with the same args, then finish(reason="no_jobs")
- If scrape returns an error → retry scrape_jobs once, then finish(reason="error")
- If score_and_filter returns 0 approved jobs → skip step 3, call finish(reason="no_matching_jobs")
- Do not call the same tool more than twice in a row
- Never stop without calling finish
"""


class ManagerAgent:
    def __init__(self, sse_queue: asyncio.Queue, settings: dict, run_id: str):
        self.sse_queue = sse_queue
        self.settings = settings
        self.run_id = run_id
        self.state = AgentState(run_id=run_id)

        # Job data cache keyed by job_id — populated by _tool_scrape_jobs
        self._job_cache: dict[str, dict] = {}

        # Build LLM client for the manager's own reasoning
        self._llm = self._build_llm()

    def _build_llm(self) -> AsyncOpenAI:
        model_name = self.settings.get("model", "gpt-4o-mini")
        if model_name == "qwen-max":
            return AsyncOpenAI(
                api_key=self.settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", ""),
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            )
        return AsyncOpenAI(
            api_key=self.settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", ""),
        )

    def _model_name(self) -> str:
        return self.settings.get("model", "gpt-4o-mini")

    async def _emit(self, event: dict):
        await self.sse_queue.put(event)

    async def _emit_thinking(self, thought: str):
        await self._emit({
            "type": "react_thinking",
            "thought": thought,
            "timestamp": _now(),
        })

    # -------------------------------------------------------------------------
    # Tool implementations (what actually runs when the LLM calls a tool)
    # -------------------------------------------------------------------------

    async def _tool_scrape_jobs(self, search_url: str, max_jobs: int) -> dict:
        from agents.scraper import ScraperAgent

        keywords = self.state.keywords
        scraper = ScraperAgent(self.settings, self.sse_queue)
        result = await scraper.run(keywords=keywords, max_jobs=max_jobs, search_url=search_url)

        if not result.success:
            return {
                "success": False,
                "error": result.error or "Unknown scraper error",
                "login_required": result.login_required,
                "jobs_scraped": 0,
                "jobs_after_filter": 0,
                "job_summaries": [],
            }

        # Apply deterministic filters (budget/type/experience from settings)
        before = len(result.jobs)
        filtered = _apply_filters(result.jobs, self.settings)[:max_jobs]
        filtered_out = before - len(filtered)

        if filtered_out > 0:
            await self._emit({"type": "log", "level": "info",
                              "message": f"Filtered out {filtered_out} jobs by budget/type/experience settings"})

        # Assign IDs and cache full job data
        summaries = []
        for raw in filtered:
            job_id = raw.get("id") or _extract_id_from_url(raw.get("job_url", ""))
            if not job_id:
                job_id = str(uuid.uuid4())[:16]
            raw["id"] = job_id
            self._job_cache[job_id] = raw
            summaries.append({
                "id": job_id,
                "title": raw.get("title", "Untitled"),
                "budget": raw.get("budget", ""),
                "job_type": raw.get("job_type", ""),
                "experience": raw.get("experience", ""),
            })

        self.state.scraped_jobs = filtered

        return {
            "success": True,
            "login_required": False,
            "jobs_scraped": before,
            "jobs_after_filter": len(filtered),
            "job_summaries": summaries,
        }

    async def _tool_score_and_filter_jobs(self, job_ids: list, score_threshold: float = 0.6) -> dict:
        jobs = [self._job_cache[jid] for jid in job_ids if jid in self._job_cache]
        if not jobs:
            return {"success": False, "error": "No valid job IDs found in cache", "approved": [], "skipped": []}

        enable_scoring = str(self.settings.get("enable_job_scoring", "false")).lower() in ("true", "1", "yes")

        if enable_scoring:
            from agents.scorer import JobScorerAgent
            scorer = JobScorerAgent(self.settings, self.sse_queue)
            result = await scorer.run(jobs, score_threshold=score_threshold)
            scored = result.scored_jobs
        else:
            scored = [ScoredJob(job=j, score=1.0, reason="scoring disabled", should_apply=True) for j in jobs]

        self.state.scored_jobs = scored

        approved = []
        skipped_out = []

        for s in scored:
            jid = s.job.get("id", "")
            if s.should_apply:
                approved.append({"id": jid, "title": s.job.get("title", ""), "score": s.score, "reason": s.reason})
            else:
                skipped_out.append({"id": jid, "title": s.job.get("title", ""), "score": s.score, "reason": s.reason})
                await self._emit({"type": "job_skipped", "job_id": jid,
                                   "reason": f"low score ({s.score:.2f}): {s.reason}"})
                await self._emit({"type": "log", "level": "info",
                                  "message": f"Skipped (score={s.score:.2f}): {s.job.get('title', jid)}"})

        return {
            "success": True,
            "approved_count": len(approved),
            "skipped_count": len(skipped_out),
            "approved": approved,
            "skipped": skipped_out,
        }

    async def _tool_generate_cover_letters(self, job_ids: list) -> dict:
        from agents.cover_letter_agent import CoverLetterAgent
        from services.jobs import job_exists, upsert_job, get_job_counts
        from notifications import send_notification

        cover_agent = CoverLetterAgent(self.settings, self.sse_queue)
        results = []

        for job_id in job_ids:
            raw_job = self._job_cache.get(job_id)
            if not raw_job:
                results.append({"id": job_id, "success": False, "error": "Job not found in cache"})
                continue

            title = raw_job.get("title", "Untitled")
            self.state.jobs_found += 1

            if job_exists(job_id):
                await self._emit({"type": "job_skipped", "job_id": job_id, "reason": "already seen"})
                await self._emit({"type": "log", "level": "info", "message": f"Skipped (seen): {title}"})
                results.append({"id": job_id, "success": False, "error": "already seen"})
                continue

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

            await self._emit({"type": "job_found", "job_id": job_id, "title": title,
                               "budget": raw_job.get("budget", "")})
            await self._emit({"type": "log", "level": "info", "message": f"Processing: {title}"})
            await self._emit({"type": "generating_cover_letter", "job_id": job_id, "title": title})
            await self._emit({"type": "log", "level": "info",
                              "message": f"Generating cover letter for: {title}"})

            cl_result = await cover_agent.run(job_data)

            if cl_result.success:
                self.state.jobs_ready += 1
                await self._emit({
                    "type": "job_ready",
                    "job_id": job_id,
                    "title": title,
                    "job_url": raw_job.get("job_url", ""),
                })
                await self._emit({"type": "log", "level": "info", "message": f"Ready: {title}"})
                send_notification("Upwork Job Ready", title, subtitle="Cover letter generated")
                results.append({"id": job_id, "success": True, "attempts": cl_result.attempts})
            else:
                await self._emit({"type": "error", "message": cl_result.error or "Cover letter failed",
                                   "job_id": job_id})
                results.append({"id": job_id, "success": False, "error": cl_result.error})

            counts = get_job_counts()
            await self._emit({"type": "counts_updated", "counts": counts})
            await asyncio.sleep(1)

        return {
            "success": True,
            "processed": len(results),
            "ready": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
        }

    async def _dispatch_tool(self, name: str, args: dict) -> str:
        """Execute a tool call and return its JSON result as a string."""
        await self._emit({"type": "phase_changed", "from_phase": self.state.phase,
                           "to_phase": name, "timestamp": _now()})
        self.state.phase = name

        if name == "scrape_jobs":
            result = await self._tool_scrape_jobs(
                search_url=args["search_url"],
                max_jobs=int(args.get("max_jobs", self.state.max_jobs)),
            )
        elif name == "score_and_filter_jobs":
            result = await self._tool_score_and_filter_jobs(
                job_ids=args.get("job_ids", []),
                score_threshold=float(args.get("score_threshold", 0.6)),
            )
        elif name == "generate_cover_letters":
            result = await self._tool_generate_cover_letters(
                job_ids=args.get("job_ids", []),
            )
        elif name == "finish":
            result = {"acknowledged": True, "reason": args.get("reason"), "summary": args.get("summary")}
        else:
            result = {"error": f"Unknown tool: {name}"}

        return json.dumps(result)

    # -------------------------------------------------------------------------
    # Main ReAct loop
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        await self._emit({"type": "agent_started", "run_id": self.run_id, "timestamp": _now()})
        await self._emit({"type": "log", "level": "info", "message": "Agent starting up..."})

        # Parse keywords once before entering the LLM loop
        keywords = self.settings.get("keywords", [])
        if isinstance(keywords, str):
            try:
                keywords = json.loads(keywords)
            except Exception:
                keywords = [keywords]
        self.state.keywords = keywords or []
        self.state.max_jobs = int(self.settings.get("max_jobs_per_run", 10))

        if not self.state.keywords:
            await self._emit({"type": "log", "level": "warn",
                              "message": "No keywords configured. Add keywords in Settings."})
            await self._emit({"type": "agent_stopped", "reason": "done"})
            return

        query = " ".join(self.state.keywords)
        self.state.search_url = (
            f"https://www.upwork.com/nx/search/jobs/?q={quote_plus(query)}&sort=recency"
        )

        # Initial user message — the LLM's full problem statement.
        # This is what the LLM reasons through before its very first tool call.
        enable_scoring = str(self.settings.get("enable_job_scoring", "false")).lower() in ("true", "1", "yes")
        score_threshold = float(self.settings.get("score_threshold", 0.6) or 0.6)
        budget_min = self.settings.get("budget_min", 0) or "any"
        budget_max = self.settings.get("budget_max", 0) or "any"
        job_type = self.settings.get("job_type", "any") or "any"
        experience = self.settings.get("experience", "any") or "any"

        user_context = (
            f"A new Upwork job search run has been triggered. Here is everything you need to execute the workflow:\n\n"
            f"## Search parameters\n"
            f"- Keywords: {', '.join(self.state.keywords)}\n"
            f"- Max jobs to scrape: {self.state.max_jobs}\n"
            f"- Search URL (pass this directly to scrape_jobs): {self.state.search_url}\n\n"
            f"## Filters already configured (applied automatically inside scrape_jobs)\n"
            f"- Budget range: {budget_min} – {budget_max}\n"
            f"- Job type: {job_type}\n"
            f"- Experience level: {experience}\n\n"
            f"## Scoring\n"
            f"- Job scoring enabled: {enable_scoring}\n"
            f"- Score threshold (pass to score_and_filter_jobs): {score_threshold}\n\n"
            f"## What to do\n"
            f"Follow the mandatory workflow: scrape_jobs → score_and_filter_jobs → generate_cover_letters → finish.\n"
            f"Think through each step before calling a tool. Use the search URL and max_jobs above for the first call."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_context},
        ]

        try:
            for iteration in range(MAX_REACT_ITERATIONS):
                response = await self._llm.chat.completions.create(
                    model=self._model_name(),
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.2,
                )

                msg = response.choices[0].message

                # Emit the LLM's reasoning (text content before tool calls)
                if msg.content:
                    await self._emit_thinking(msg.content)
                    await self._emit({"type": "log", "level": "info",
                                      "message": f"[Manager] {msg.content}"})

                # No tool call → LLM responded with plain text (shouldn't happen often)
                if not msg.tool_calls:
                    await self._emit({"type": "log", "level": "warn",
                                      "message": "Manager LLM returned no tool call — ending run."})
                    break

                # Append assistant message to history
                messages.append(msg)

                # Execute each tool call
                finished = False
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    await self._emit({"type": "log", "level": "info",
                                      "message": f"[Manager] → calling {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:120]})"})

                    tool_result_str = await self._dispatch_tool(tool_name, tool_args)

                    # Append tool result to history
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result_str,
                    })

                    await self._emit({"type": "log", "level": "info",
                                      "message": f"[Manager] ← {tool_name} result: {tool_result_str[:200]}"})

                    if tool_name == "finish":
                        args_parsed = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        summary = args_parsed.get("summary", "")
                        reason = args_parsed.get("reason", "done")
                        if summary:
                            await self._emit({"type": "log", "level": "info",
                                              "message": f"[Manager] {summary}"})
                        finished = True

                if finished:
                    break

            else:
                await self._emit({"type": "log", "level": "warn",
                                  "message": f"Manager reached max iterations ({MAX_REACT_ITERATIONS}) — stopping."})

        except asyncio.CancelledError:
            await self._emit({"type": "agent_stopped", "reason": "cancelled"})
            return
        except Exception as e:
            logger.error(f"Manager agent error: {e}", exc_info=True)
            await self._emit({"type": "error", "message": str(e)})
            await self._emit({"type": "agent_stopped", "reason": "error"})
            return

        await self._emit({
            "type": "done",
            "jobs_found": self.state.jobs_found,
            "jobs_ready": self.state.jobs_ready,
        })
        await self._emit({"type": "agent_stopped", "reason": "done"})
        await self._emit({
            "type": "log",
            "level": "info",
            "message": f"Done. Found: {self.state.jobs_found}, Ready: {self.state.jobs_ready}",
        })


async def run_manager_agent(sse_queue: asyncio.Queue, settings: dict, run_id: str) -> None:
    """Entry point called from main.py."""
    manager = ManagerAgent(sse_queue, settings, run_id)
    await manager.run()
