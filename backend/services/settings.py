"""Settings CRUD — all settings stored as key/value in SQLite."""

import json
from database.db import get_db


def get_all_settings() -> dict:
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = {}
    for row in rows:
        key, value = row["key"], row["value"]
        # Deserialise JSON arrays/numbers when possible
        try:
            result[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            result[key] = value
    return result


def update_settings(updates: dict) -> dict:
    conn = get_db()
    for key, value in updates.items():
        # Serialise lists/dicts to JSON strings
        if isinstance(value, (list, dict)):
            serialised = json.dumps(value)
        else:
            serialised = str(value)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, serialised),
        )
    conn.commit()
    return get_all_settings()
