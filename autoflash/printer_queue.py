"""Single-thread queue around the Brother QL label printer.

The printer accepts one TCP connection at a time and a print job is a single
opaque byte stream. If two workers send concurrently, output interleaves and
both labels are corrupted. This module owns one worker thread that drains a
queue of (kind, payload) jobs.

Usage:
    pq = PrinterQueue(host="printer.local")
    pq.start()
    pq.print_wifi(metadata)
    pq.print_login(metadata, bootloader_pw)
    ...
    pq.stop()
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from labelprinter import labels, printer


_log = logging.getLogger(__name__)


@dataclass
class _Job:
    kind: str  # "wifi" | "login"
    metadata: dict
    bootloader_pw: str | None = None


class PrinterQueue:
    def __init__(self, host: str | None):
        self.host = host
        self._q: queue.Queue[_Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self):
        if self.host is None:
            return
        self._thread = threading.Thread(
            target=self._run, name="printer-queue", daemon=True
        )
        self._thread.start()

    def stop(self, drain: bool = True):
        if self._thread is None:
            return
        if drain:
            self._q.join()
        self._q.put(None)
        self._thread.join()
        self._thread = None

    def print_wifi(self, metadata: dict):
        if self.host is None:
            _log.info("No labelprinter set, skipping wifi label")
            return
        self._q.put(_Job("wifi", metadata))

    def print_login(self, metadata: dict, bootloader_pw: str):
        if self.host is None:
            _log.info("No labelprinter set, skipping login label")
            return
        self._q.put(_Job("login", metadata, bootloader_pw))

    def _run(self):
        while True:
            job = self._q.get()
            try:
                if job is None:
                    return
                self._do_print(job)
            except Exception:
                _log.exception("Printer job failed")
            finally:
                self._q.task_done()

    def _do_print(self, job: _Job):
        if job.kind == "wifi":
            surf = labels.render_wifi(
                ssid=job.metadata["ssid"],
                password=job.metadata["wifi_password"],
            )
        elif job.kind == "login":
            surf = labels.render_login(
                ip="192.168.0.1",
                password=job.metadata["root_password"],
                bootloader_pw=job.bootloader_pw,
            )
        else:
            raise ValueError(f"Unknown job kind: {job.kind}")
        printer.print_to_ip(surf, self.host)
