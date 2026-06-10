import sqlite3
import hashlib
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class Job:
    id: int
    message_id: str
    phone: str
    body: str
    received_at: str
    enqueued_at: str
    status: str
    attempt_count: int
    last_attempt_at: Optional[str]
    fail_reason: Optional[str]
    reply_sent: Optional[str]
    sim_used: Optional[int]
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row) -> Job:
    return Job(
        id=row[0], message_id=row[1], phone=row[2], body=row[3],
        received_at=row[4], enqueued_at=row[5], status=row[6],
        attempt_count=row[7], last_attempt_at=row[8], fail_reason=row[9],
        reply_sent=row[10], sim_used=row[11], updated_at=row[12],
    )


class QueueManager:
    def __init__(self, db_path: str, max_retry_attempts: int = 3, dedup_retention_days: int = 90):
        self.db_path = db_path
        self.max_retry = max_retry_attempts
        self.dedup_retention = dedup_retention_days
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        import os
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path) as f:
            schema = f.read()
        with self._conn() as conn:
            conn.executescript(schema)

    def is_duplicate(self, message_id: str, phone: str, body: str, received_at: str) -> bool:
        # Layer 1: message_id already in queue (any status) — primary check
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM jobs WHERE message_id = ?", (message_id,)).fetchone()
            if row:
                return True
            # Layer 2: hash fallback for SMS DB resets (uses full timestamp, not date-only,
            # to avoid false positives when the same person sends the same text twice in a day)
            h = self._make_hash(phone, body, received_at)
            row = conn.execute("SELECT 1 FROM dedup_hashes WHERE hash = ?", (h,)).fetchone()
            return bool(row)

    def _make_hash(self, phone: str, body: str, received_at: str) -> str:
        return hashlib.sha256(f"{phone}|{body}|{received_at}".encode()).hexdigest()

    def _store_dedup_hash(self, conn, phone: str, body: str, received_at: str):
        h = self._make_hash(phone, body, received_at)
        conn.execute(
            "INSERT OR IGNORE INTO dedup_hashes (hash, phone, created_at) VALUES (?, ?, ?)",
            (h, phone, _now()),
        )

    def enqueue(self, message_id: str, phone: str, body: str, received_at: str) -> int:
        now = _now()
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO jobs
                       (message_id, phone, body, received_at, enqueued_at, status, attempt_count, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)""",
                    (message_id, phone, body, received_at, now, now),
                )
                self._store_dedup_hash(conn, phone, body, received_at)
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT id FROM jobs WHERE message_id = ?", (message_id,)).fetchone()
                return row[0] if row else -1

    def get_next_pending(self) -> Optional[Job]:
        with self._conn() as conn:
            now = _now()
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' ORDER BY enqueued_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            job_id = row[0]
            conn.execute(
                "UPDATE jobs SET status = 'processing', last_attempt_at = ?, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )
            updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _row_to_job(updated)

    def mark_done(self, job_id: int, reply_sent: str, sim_used: Optional[int]):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done', reply_sent = ?, sim_used = ?, updated_at = ? WHERE id = ?",
                (reply_sent, sim_used, now, job_id),
            )

    def mark_skipped(self, job_id: int, reason: str):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'skipped', fail_reason = ?, updated_at = ? WHERE id = ?",
                (reason, now, job_id),
            )

    def mark_held(self, job_id: int, reason: str):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'held', fail_reason = ?, updated_at = ? WHERE id = ?",
                (reason, now, job_id),
            )

    def mark_failed(self, job_id: int, reason: str):
        now = _now()
        with self._conn() as conn:
            row = conn.execute("SELECT attempt_count FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return
            attempts = row[0] + 1
            if attempts >= self.max_retry:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', attempt_count = ?, fail_reason = ?, updated_at = ? WHERE id = ?",
                    (attempts, reason, now, job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = 'pending', attempt_count = ?, fail_reason = ?, updated_at = ? WHERE id = ?",
                    (attempts, reason, now, job_id),
                )

    def recover_stale_processing(self):
        now = _now()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, attempt_count FROM jobs WHERE status = 'processing'"
            ).fetchall()
            for row in rows:
                job_id, attempts = row[0], row[1]
                if attempts >= self.max_retry:
                    conn.execute(
                        "UPDATE jobs SET status = 'failed', fail_reason = 'stale_processing', updated_at = ? WHERE id = ?",
                        (now, job_id),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status = 'pending', updated_at = ? WHERE id = ?",
                        (now, job_id),
                    )

    def purge_old_dedup_hashes(self):
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.dedup_retention)).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM dedup_hashes WHERE created_at < ?", (cutoff,))

    def recent_reply_count(self, phone: str, window_minutes: int) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE phone = ? AND status = 'done' AND updated_at >= ?",
                (phone, cutoff),
            ).fetchone()
            return row[0] if row else 0

    def list_by_status(self, status: str) -> List[Job]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY enqueued_at DESC", (status,)
            ).fetchall()
            return [_row_to_job(r) for r in rows]

    def list_held(self) -> List[Job]:
        return self.list_by_status("held")

    def list_pending(self) -> List[Job]:
        return self.list_by_status("pending")

    def get_job(self, job_id: int) -> Optional[Job]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _row_to_job(row) if row else None

    def status_counts(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ).fetchall()
            return {r[0]: r[1] for r in rows}

    def delete_by_status(self, status: str) -> int:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE status = ?", (status,))
            return cursor.rowcount

    def update_job_reply(self, job_id: int, reply_text: str):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET reply_sent = ?, updated_at = ? WHERE id = ?",
                (reply_text, now, job_id),
            )
