import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def get_json(self, key: str, default=None):
        val = self.get(key)
        if val is None:
            return default
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default

    def set(self, key: str, value: str):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )

    def set_json(self, key: str, value):
        self.set(key, json.dumps(value))

    def increment(self, key: str) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            current = int(row[0]) if row else 0
            new_val = current + 1
            now = _now()
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(new_val), now),
            )
            return new_val

    def reset_daily_stats(self):
        self.set("stats_today_sent", "0")
        self.set("stats_today_skipped", "0")

    def get_stats_today_sent(self) -> int:
        val = self.get("stats_today_sent")
        return int(val) if val else 0

    def get_stats_today_skipped(self) -> int:
        val = self.get("stats_today_skipped")
        return int(val) if val else 0
