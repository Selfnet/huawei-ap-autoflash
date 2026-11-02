import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from autoflash.history import FlashHistory


class FlashHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "history.sqlite"
        self.history = FlashHistory(self.path)

    def start(self, ap_index=0):
        return self.history.start(
            batch_id="batch", ap_index=ap_index, serial_port=f"/dev/ttyUSB{ap_index}",
            baudrate=9600, switch_host="switch", switch_port=f"ge-0/0/{ap_index}",
            images_dir="/images", log_path="/logs/ap.log", ramboot_image="ramboot.bin",
            tftp_ip="192.168.1.10", openwrt_default_ip="192.168.1.1", config_json="{}",
        )

    def test_persists_unfinished_attempt_without_claiming_success(self):
        attempt = self.start()
        self.history.record(attempt, "running_sysupgrade", changes={"stage": "sysupgrade"})
        FlashHistory(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT state, stage, finished_at FROM flash_attempts WHERE id = ?",
                (attempt,),
            ).fetchone()
        self.assertEqual(row, ("running", "sysupgrade", None))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_failure_retains_last_stage_and_error(self):
        attempt = self.start()
        self.history.record(attempt, "waiting_for_ping", changes={"stage": "waiting_for_ping"})
        self.history.finish(attempt, "failed", RuntimeError("AP unreachable"))
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute(
                "SELECT state, stage, error_type, error_message, finished_at "
                "FROM flash_attempts WHERE id = ?", (attempt,),
            ).fetchone()
        self.assertEqual(row[:4], ("failed", "waiting_for_ping", "RuntimeError", "AP unreachable"))
        self.assertIsNotNone(row[4])

    def test_parallel_attempts_and_events_are_not_mixed(self):
        def worker(index):
            attempt = self.start(index)
            self.history.record(attempt, "custom", index=index)
            self.history.finish(attempt, "succeeded")
            return attempt

        with ThreadPoolExecutor(max_workers=8) as pool:
            attempts = list(pool.map(worker, range(16)))
        self.assertEqual(len(set(attempts)), 16)
        with closing(sqlite3.connect(self.path)) as con:
            rows = con.execute(
                "SELECT a.ap_index, e.details_json FROM flash_attempts a "
                "JOIN flash_events e ON a.id = e.attempt_id WHERE e.event = 'custom'"
            ).fetchall()
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM flash_attempts WHERE state = 'succeeded'"
            ).fetchone()[0], 16)
        self.assertEqual(len(rows), 16)
        for index, details in rows:
            self.assertEqual(json.loads(details), {"index": index})

    def test_event_and_update_are_atomic(self):
        attempt = self.start()
        with self.assertRaises(TypeError):
            self.history.record(
                attempt, "bad", changes={"stage": "not_committed"}, invalid=object()
            )
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute(
                "SELECT stage FROM flash_attempts WHERE id = ?", (attempt,)
            ).fetchone()[0], "starting")
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM flash_events WHERE event = 'bad'"
            ).fetchone()[0], 0)
