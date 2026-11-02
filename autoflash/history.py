"""Persistent flash attempts and structured events."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FlashHistory:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(self._connect()) as con, con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS flash_attempts (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    ap_index INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    state TEXT NOT NULL CHECK (
                        state IN ('running', 'succeeded', 'failed', 'aborted', 'interrupted')
                    ),
                    stage TEXT NOT NULL,
                    serial_port TEXT NOT NULL,
                    baudrate INTEGER NOT NULL,
                    switch_host TEXT NOT NULL,
                    switch_port TEXT NOT NULL,
                    images_dir TEXT NOT NULL,
                    log_path TEXT NOT NULL,
                    ramboot_image TEXT NOT NULL,
                    tftp_ip TEXT NOT NULL,
                    openwrt_default_ip TEXT NOT NULL,
                    flash_ip TEXT,
                    image_name TEXT,
                    image_path TEXT,
                    image_sha256 TEXT,
                    image_size_bytes INTEGER,
                    metadata_filename TEXT,
                    metadata_raw TEXT,
                    metadata_json TEXT,
                    network_json TEXT NOT NULL DEFAULT '{}',
                    config_json TEXT NOT NULL,
                    poe_state TEXT NOT NULL DEFAULT 'unknown',
                    error_type TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS flash_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES flash_attempts(id),
                    occurred_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS flash_attempts_started
                    ON flash_attempts(started_at);
                CREATE INDEX IF NOT EXISTS flash_events_attempt
                    ON flash_events(attempt_id, id);
            """)

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def start(self, **fields) -> str:
        attempt_id = uuid.uuid4().hex
        now = _now()
        fields.update(
            id=attempt_id,
            started_at=now,
            updated_at=now,
            state="running",
            stage="starting",
        )
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        with closing(self._connect()) as con, con:
            con.execute(
                f"INSERT INTO flash_attempts ({columns}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
            self._event(con, attempt_id, now, "started", {})
        return attempt_id

    def record(self, attempt_id: str, event: str, *, changes=None, **details):
        changes = dict(changes or {})
        now = _now()
        changes["updated_at"] = now
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with closing(self._connect()) as con, con:
            con.execute(
                f"UPDATE flash_attempts SET {assignments} WHERE id = ?",
                (*changes.values(), attempt_id),
            )
            self._event(con, attempt_id, now, event, details)

    def finish(
        self, attempt_id: str, state: str, error: BaseException | None = None, **changes
    ):
        changes.update(
            state=state,
            finished_at=_now(),
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
        )
        if state == "succeeded":
            changes["stage"] = "complete"
        self.record(
            attempt_id,
            state,
            changes=changes,
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
        )

    @staticmethod
    def _event(con, attempt_id, now, event, details):
        con.execute(
            "INSERT INTO flash_events (attempt_id, occurred_at, event, details_json) "
            "VALUES (?, ?, ?, ?)",
            (attempt_id, now, event, json.dumps(details, ensure_ascii=False)),
        )
