import hashlib
import ipaddress
import json
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autoflash import parallel
from autoflash.interaction.serial import AbortedError


class ParallelHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.metadata = {
            "ssid": "Test WiFi", "wifi_password": "wifi-secret",
            "root_password": "root-secret", "extra": {"unicode": "Grüße", "flags": [True, 7]},
        }
        (self.images / "test.json").write_text(json.dumps(self.metadata))
        (self.images / "test.bin").write_bytes(b"firmware")
        self.ctx = parallel.Context(
            images_dir=self.images, logs_dir=self.logs, baudrate=9600,
            bootloader_password="boot-secret", printer=SimpleNamespace(host="printer"),
            timestamp="batch", history_db=self.root / "history.sqlite",
            old_uboot_passwords=["old-secret"],
        )
        self.enable = self.mock("autoflash.parallel.poe.enable_one")
        self.disable = self.mock("autoflash.parallel.poe.disable_one")
        self.mock("autoflash.parallel.time.sleep")
        self.mock("autoflash.parallel.get_free_ip", return_value=ipaddress.IPv4Address("192.168.1.23"))
        mkdtemp = tempfile.mkdtemp
        self.mock("autoflash.parallel.tempfile.mkdtemp", side_effect=lambda **kw: mkdtemp(dir=self.root, **kw))
        self.run = self.mock("autoflash.parallel.run_autoflash", side_effect=self.successful_flash)
        self.statuses = []

    def mock(self, name, **kwargs):
        patcher = patch(name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def successful_flash(self, **kwargs):
        kwargs["progress"]("running_sysupgrade", image_name="test.bin", options="-n -v")
        kwargs["progress"]("network", phase="installed", interfaces={
            "br-lan": {"mac": "aa:bb:cc:dd:ee:ff", "ipv4": ["192.168.1.1/24"]},
        })

    def flash(self):
        return parallel.flash_one(0, self.ctx, lambda ap, event, **fields: self.statuses.append((event, fields)))

    def attempts(self):
        with closing(sqlite3.connect(self.ctx.history.path)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute("SELECT * FROM flash_attempts ORDER BY rowid")]

    def events(self, attempt):
        with closing(sqlite3.connect(self.ctx.history.path)) as con:
            return con.execute(
                "SELECT event, details_json FROM flash_events WHERE attempt_id = ? ORDER BY id",
                (attempt["id"],),
            ).fetchall()

    def test_success_records_full_metadata_image_network_and_configuration(self):
        self.assertTrue(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "succeeded")
        self.assertEqual(attempt["stage"], "complete")
        self.assertIsNotNone(attempt["finished_at"])
        self.assertIsNone(attempt["error_type"])
        self.assertEqual(json.loads(attempt["metadata_json"]), self.metadata)
        self.assertEqual(json.loads(attempt["metadata_raw"]), self.metadata)
        self.assertEqual(attempt["image_name"], "test.bin")
        self.assertEqual(attempt["metadata_filename"], "test.json")
        self.assertEqual(attempt["image_sha256"], hashlib.sha256(b"firmware").hexdigest())
        self.assertEqual(attempt["image_size_bytes"], 8)
        self.assertEqual(attempt["flash_ip"], "192.168.1.23")
        self.assertEqual(attempt["tftp_ip"], "192.168.1.10")
        self.assertEqual(attempt["openwrt_default_ip"], "192.168.1.1")
        self.assertEqual(attempt["serial_port"], "/dev/ttyUSB0")
        self.assertEqual(attempt["poe_state"], "off")
        network = json.loads(attempt["network_json"])
        self.assertEqual(network["installed"]["br-lan"]["mac"], "aa:bb:cc:dd:ee:ff")
        config = json.loads(attempt["config_json"])
        self.assertEqual(config["bootloader_password"], "boot-secret")
        self.assertEqual(config["old_uboot_passwords"], ["old-secret"])
        self.assertTrue(Path(attempt["log_path"]).exists())
        self.assertEqual(self.statuses[-1][0], "done")
        self.assertEqual(self.events(attempt)[-1][0], "succeeded")

    def test_failure_records_error_and_restores_image(self):
        def fail(**kwargs):
            kwargs["progress"]("running_sysupgrade")
            raise RuntimeError("sysupgrade failed")

        self.run.side_effect = fail
        self.assertFalse(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "failed")
        self.assertEqual(attempt["stage"], "running_sysupgrade")
        self.assertEqual(attempt["error_type"], "RuntimeError")
        self.assertEqual(attempt["error_message"], "sysupgrade failed")
        self.assertEqual(json.loads(attempt["metadata_json"]), self.metadata)
        self.assertTrue((self.images / "test.json").exists())
        self.assertTrue((self.images / "test.bin").exists())
        self.assertIn("image_restored", [event for event, _ in self.events(attempt)])
        self.disable.assert_called_once_with(0)

    def test_abort_is_distinct_from_failure_and_keeps_image_for_restart(self):
        def abort(**kwargs):
            kwargs["cancel_event"].set()
            raise AbortedError()

        self.run.side_effect = abort
        self.assertFalse(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "aborted")
        self.assertEqual(attempt["error_type"], "AbortedError")
        self.assertTrue(Path(attempt["image_path"]).exists())
        self.assertFalse((self.images / "test.json").exists())
        self.disable.assert_called_once_with(0)

    def test_restart_creates_a_separate_attempt_with_reused_image(self):
        self.assertTrue(self.flash())
        claim = next(fields["claim"] for event, fields in self.statuses if event == "metadata")
        self.ctx.reuse[0] = claim
        self.assertTrue(self.flash())
        first, second = self.attempts()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["image_sha256"], second["image_sha256"])
        self.assertEqual(json.loads(next(
            details for event, details in self.events(second) if event == "image_claimed"
        )), {"reused": True})

    def test_invalid_metadata_is_preserved_and_flash_does_not_start(self):
        (self.images / "test.json").write_text("{invalid")
        self.assertFalse(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "failed")
        self.assertEqual(attempt["metadata_raw"], "{invalid")
        self.assertEqual(attempt["error_type"], "JSONDecodeError")
        self.assertIsNone(attempt["metadata_json"])
        self.enable.assert_not_called()
        self.run.assert_not_called()

    def test_no_image_still_records_failure(self):
        (self.images / "test.bin").unlink()
        self.assertFalse(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "failed")
        self.assertEqual(attempt["stage"], "claiming_image")
        self.assertEqual(attempt["error_type"], "FileNotFoundError")
        self.enable.assert_not_called()

    def test_keep_poe_is_recorded(self):
        self.ctx.keep_poe_on = True
        self.assertTrue(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["poe_state"], "on")
        self.assertIn("poe_kept", [event for event, _ in self.events(attempt)])
        self.disable.assert_not_called()

    def test_poe_shutdown_failure_does_not_claim_flash_failed(self):
        self.disable.side_effect = RuntimeError("switch unavailable")
        self.assertTrue(self.flash())
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "succeeded")
        self.assertEqual(attempt["poe_state"], "unknown")
        details = next(details for event, details in self.events(attempt) if event == "poe_off_failed")
        self.assertEqual(json.loads(details)["error_message"], "switch unavailable")

    def test_history_failure_does_not_skip_poe_or_image_cleanup(self):
        def fail_database(**kwargs):
            self.ctx.history.record = Mock(side_effect=sqlite3.OperationalError("disk full"))
            kwargs["progress"]("running_sysupgrade")

        self.run.side_effect = fail_database
        with self.assertRaises(sqlite3.OperationalError):
            self.flash()
        self.disable.assert_called_once_with(0)
        self.assertTrue((self.images / "test.json").exists())
        self.assertTrue((self.images / "test.bin").exists())
        self.assertNotIn(0, self.ctx.cancel_events)
        self.assertFalse(logging.getLogger("autoflash.ap0").handlers)

    def test_final_history_failure_does_not_return_flashed_image_to_pool(self):
        self.ctx.history.finish = Mock(side_effect=sqlite3.OperationalError("disk full"))
        with self.assertRaises(sqlite3.OperationalError):
            self.flash()
        self.disable.assert_called_once_with(0)
        attempt, = self.attempts()
        self.assertTrue(Path(attempt["image_path"]).exists())
        self.assertFalse((self.images / "test.json").exists())
        self.assertEqual(self.statuses[-1][0], "failed")
        self.assertIn("History update failed", self.statuses[-1][1]["error"])
        self.assertNotIn("done", [event for event, _ in self.statuses])
        self.assertFalse(logging.getLogger("autoflash.ap0").handlers)

    def test_interrupted_worker_does_not_claim_success(self):
        self.run.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.flash()
        attempt, = self.attempts()
        self.assertEqual(attempt["state"], "interrupted")
        self.assertEqual(attempt["error_type"], "KeyboardInterrupt")
        self.assertIsNotNone(attempt["finished_at"])
        self.disable.assert_called_once_with(0)
