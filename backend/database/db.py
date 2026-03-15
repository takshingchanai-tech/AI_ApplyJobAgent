"""
SQLite database connection and schema initialization.
WAL mode for concurrent reads during agent scraping.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "upwork_agent.db"

_conn: Optional[sqlite3.Connection] = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                TEXT PRIMARY KEY,
            title             TEXT NOT NULL,
            client_name       TEXT DEFAULT '',
            budget            TEXT DEFAULT '',
            job_type          TEXT DEFAULT '',
            experience        TEXT DEFAULT '',
            description       TEXT DEFAULT '',
            skills            TEXT DEFAULT '[]',
            job_url           TEXT NOT NULL,
            status            TEXT DEFAULT 'seen',
            cover_letter_text TEXT DEFAULT '',
            cover_letter_pdf  TEXT DEFAULT '',
            connects_required INTEGER DEFAULT 6,
            found_at          TEXT DEFAULT (datetime('now')),
            applied_at        TEXT,
            updated_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        INSERT OR IGNORE INTO settings(key, value) VALUES
            ('model',             'gpt-4o-mini'),
            ('keywords',          '[]'),
            ('budget_min',        '0'),
            ('budget_max',        '0'),
            ('job_type',          'any'),
            ('experience',        'any'),
            ('max_jobs_per_run',  '10'),
            ('chrome_profile',    ''),
            ('freelancer_name',   ''),
            ('freelancer_skills', '[]'),
            ('freelancer_bio',    ''),
            ('resume_path',       ''),
            ('portfolio_path',    '');
    """)
    conn.commit()
    logger.info("Database schema initialized")
