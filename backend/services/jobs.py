"""Job CRUD operations."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from database.db import get_db


def _row_to_dict(row) -> dict:
    d = dict(row)
    # Deserialise skills JSON array
    try:
        d["skills"] = json.loads(d.get("skills", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["skills"] = []
    return d


def list_jobs(status: Optional[str] = None) -> List[dict]:
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY found_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY found_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job_counts() -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    counts = {"seen": 0, "ready": 0, "applying": 0, "applied": 0, "skipped": 0}
    for row in rows:
        counts[row["status"]] = row["cnt"]
    # "past" = applied + skipped
    counts["past"] = counts["applied"] + counts["skipped"]
    return counts


def get_job(job_id: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def upsert_job(data: dict) -> dict:
    """Insert or update a job record. Returns the saved job."""
    conn = get_db()
    job_id = data.get("id") or str(uuid.uuid4())
    skills = data.get("skills", [])
    skills_json = json.dumps(skills) if isinstance(skills, list) else skills

    conn.execute(
        """
        INSERT INTO jobs (id, title, client_name, budget, job_type, experience,
                          description, skills, job_url, status, cover_letter_text,
                          cover_letter_pdf, connects_required)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title             = excluded.title,
            client_name       = excluded.client_name,
            budget            = excluded.budget,
            job_type          = excluded.job_type,
            experience        = excluded.experience,
            description       = excluded.description,
            skills            = excluded.skills,
            job_url           = excluded.job_url,
            status            = excluded.status,
            cover_letter_text = excluded.cover_letter_text,
            cover_letter_pdf  = excluded.cover_letter_pdf,
            connects_required = excluded.connects_required,
            updated_at        = datetime('now')
        """,
        (
            job_id,
            data.get("title", ""),
            data.get("client_name", ""),
            data.get("budget", ""),
            data.get("job_type", ""),
            data.get("experience", ""),
            data.get("description", ""),
            skills_json,
            data.get("job_url", ""),
            data.get("status", "seen"),
            data.get("cover_letter_text", ""),
            data.get("cover_letter_pdf", ""),
            data.get("connects_required", 6),
        ),
    )
    conn.commit()
    return get_job(job_id)


def update_job(job_id: str, updates: dict) -> Optional[dict]:
    job = get_job(job_id)
    if not job:
        return None
    conn = get_db()
    allowed = {
        "status", "cover_letter_text", "cover_letter_pdf",
        "applied_at", "title", "budget", "description",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return job

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    set_clause += ", updated_at = datetime('now')"
    params = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", params)
    conn.commit()
    return get_job(job_id)


def delete_job(job_id: str) -> bool:
    conn = get_db()
    result = conn.execute(
        "UPDATE jobs SET status = 'skipped', updated_at = datetime('now') WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    return result.rowcount > 0


def job_exists(job_id: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is not None
