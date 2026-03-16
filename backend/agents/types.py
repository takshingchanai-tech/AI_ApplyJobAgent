"""
Shared Pydantic contracts between manager and sub-agents.
"""

from typing import List, Optional
from pydantic import BaseModel


class ScraperResult(BaseModel):
    success: bool
    jobs: List[dict]
    error: Optional[str] = None
    login_required: bool = False


class ScoredJob(BaseModel):
    job: dict
    score: float          # 0.0–1.0
    reason: str
    should_apply: bool


class ScorerResult(BaseModel):
    success: bool
    scored_jobs: List[ScoredJob]
    error: Optional[str] = None


class CoverLetterResult(BaseModel):
    success: bool
    job_id: str
    cover_letter_text: str = ""
    pdf_path: str = ""
    error: Optional[str] = None
    attempts: int = 1


class AgentState(BaseModel):
    run_id: str
    phase: str = "init"       # init | scraping | scoring | generating | done | error
    keywords: List[str] = []
    search_url: str = ""
    max_jobs: int = 10
    scraped_jobs: List[dict] = []
    scored_jobs: List[ScoredJob] = []
    jobs_found: int = 0
    jobs_ready: int = 0
    scraper_attempts: int = 0
