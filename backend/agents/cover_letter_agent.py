"""
CoverLetterAgent — LLM cover letter generation with retry logic.
"""

import asyncio
import logging

from agents.types import CoverLetterResult

logger = logging.getLogger(__name__)


class CoverLetterAgent:
    def __init__(self, settings: dict, sse_queue: asyncio.Queue):
        self.settings = settings
        self.sse_queue = sse_queue

    async def _emit(self, event: dict):
        await self.sse_queue.put(event)

    async def run(self, job: dict, max_attempts: int = 3) -> CoverLetterResult:
        """
        Generate cover letter with retry logic. Never raises — wraps all errors
        in CoverLetterResult.error. On final failure, job stays 'seen'.
        """
        from cover_letter import generate_cover_letter_text, generate_pdf
        from services.jobs import update_job

        job_id = job.get("id", "")
        title = job.get("title", "Untitled")

        for attempt in range(1, max_attempts + 1):
            try:
                cover_text = await generate_cover_letter_text(job, self.settings)
                pdf_path = generate_pdf(job_id, cover_text)

                update_job(job_id, {
                    "status": "ready",
                    "cover_letter_text": cover_text,
                    "cover_letter_pdf": pdf_path,
                })

                return CoverLetterResult(
                    success=True,
                    job_id=job_id,
                    cover_letter_text=cover_text,
                    pdf_path=pdf_path,
                    attempts=attempt,
                )

            except Exception as e:
                if attempt < max_attempts:
                    wait = 2 ** attempt  # 2s, 4s
                    await self._emit({
                        "type": "log",
                        "level": "warn",
                        "message": f"Cover letter attempt {attempt} failed for '{title}': {e}. Retrying in {wait}s...",
                    })
                    await asyncio.sleep(wait)
                else:
                    await self._emit({
                        "type": "log",
                        "level": "error",
                        "message": f"Cover letter failed after {max_attempts} attempts for '{title}': {e}. Job saved as 'seen' — retry from the Pending tab.",
                    })
                    return CoverLetterResult(
                        success=False,
                        job_id=job_id,
                        error=str(e),
                        attempts=attempt,
                    )

        # Should not reach here
        return CoverLetterResult(success=False, job_id=job_id, error="Unexpected exit from retry loop")
