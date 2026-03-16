"""
JobScorerAgent — optional LLM-based job fit scoring.
Off by default (enable_job_scoring setting, default False).
"""

import asyncio
import json
import logging
import os

from agents.types import ScoredJob, ScorerResult

logger = logging.getLogger(__name__)


class JobScorerAgent:
    def __init__(self, settings: dict, sse_queue: asyncio.Queue):
        self.settings = settings
        self.sse_queue = sse_queue

    async def _emit(self, event: dict):
        await self.sse_queue.put(event)

    def _pass_through(self, jobs: list) -> ScorerResult:
        """Return all jobs with score=1.0 (pass-through, never blocks pipeline)."""
        scored = [
            ScoredJob(job=j, score=1.0, reason="scoring skipped", should_apply=True)
            for j in jobs
        ]
        return ScorerResult(success=True, scored_jobs=scored)

    async def run(self, jobs: list, score_threshold: float = 0.6) -> ScorerResult:
        """
        Score jobs by fit in a single batch LLM call.
        On any failure, returns pass-through (score=1.0) — never blocks pipeline.
        """
        if not jobs:
            return ScorerResult(success=True, scored_jobs=[])

        await self._emit({"type": "log", "level": "info",
                          "message": f"Scoring {len(jobs)} jobs for fit..."})

        try:
            from openai import AsyncOpenAI

            model_name = self.settings.get("model", "gpt-4o-mini")
            openai_api_key = self.settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
            dashscope_api_key = self.settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", "")

            if model_name == "qwen-max":
                client = AsyncOpenAI(
                    api_key=dashscope_api_key,
                    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                )
            else:
                client = AsyncOpenAI(api_key=openai_api_key)

            freelancer_bio = self.settings.get("freelancer_bio", "")
            freelancer_skills = self.settings.get("freelancer_skills", [])
            if isinstance(freelancer_skills, list):
                skills_str = ", ".join(freelancer_skills)
            else:
                skills_str = str(freelancer_skills)

            job_summaries = []
            for j in jobs:
                job_id = j.get("id", "")
                title = j.get("title", "")
                desc = (j.get("description", "") or "")[:300]
                skills = ", ".join(j.get("skills", []) or [])
                job_summaries.append(f'- id: {job_id}\n  title: {title}\n  description: {desc}\n  skills: {skills}')

            jobs_text = "\n".join(job_summaries)

            prompt = f"""You are evaluating job fit for a freelancer.

Freelancer profile:
Bio: {freelancer_bio}
Skills: {skills_str}

Jobs to evaluate:
{jobs_text}

For each job, output a JSON array with objects having these fields:
- job_id: string (must match the id field exactly)
- score: float between 0.0 and 1.0 (1.0 = perfect fit, 0.0 = no fit)
- reason: brief one-sentence explanation

Return ONLY valid JSON array, no markdown, no explanation:
[{{"job_id": "...", "score": 0.8, "reason": "..."}}]"""

            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.2,
            )

            result_text = response.choices[0].message.content or ""

            # Parse JSON result
            clean = result_text.strip()
            start = clean.find('[')
            end = clean.rfind(']')
            if start != -1 and end > start:
                score_data = json.loads(clean[start:end + 1])
            else:
                raise ValueError(f"Could not parse scorer response: {result_text[:200]}")

            # Map scores back to jobs
            score_map = {item["job_id"]: item for item in score_data}

            scored_jobs = []
            for j in jobs:
                job_id = j.get("id", "")
                if job_id in score_map:
                    s = score_map[job_id]
                    scored_jobs.append(ScoredJob(
                        job=j,
                        score=s["score"],
                        reason=s.get("reason", ""),
                        should_apply=s["score"] >= score_threshold,
                    ))
                else:
                    # Job not scored — include with score=1.0
                    scored_jobs.append(ScoredJob(
                        job=j,
                        score=1.0,
                        reason="not scored by LLM",
                        should_apply=True,
                    ))

            passed = sum(1 for s in scored_jobs if s.should_apply)
            await self._emit({"type": "log", "level": "info",
                              "message": f"Scoring complete: {passed}/{len(scored_jobs)} jobs passed threshold {score_threshold}"})

            return ScorerResult(success=True, scored_jobs=scored_jobs)

        except Exception as e:
            await self._emit({"type": "log", "level": "warn",
                              "message": f"Scorer failed ({e}), passing all jobs through"})
            return self._pass_through(jobs)
