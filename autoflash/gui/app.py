"""Tkinter GUI for parallel AP flashing.

Owns the worker pool, the Context, the PrinterQueue, and the event queue
that worker threads push into. The mainloop drains the queue every 50 ms and
routes events to the matching APPanel.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from tkinter import messagebox

from .. import poe
from ..parallel import Context, flash_one, make_timestamp
from ..printer_queue import PrinterQueue
from .bridge import GuiHandler
from .events import LogLine, StatusEvent, WorkerFinished
from .panel import APPanel


_log = logging.getLogger(__name__)


class App:
    def __init__(
        self,
        ap_indices: list[int],
        images_dir: Path,
        logs_dir: Path,
        baudrate: int,
        bootloader_password: str,
        labelprinter_host: str | None,
    ):
        self.ap_indices = ap_indices
        self.events: queue.Queue = queue.Queue()
        self.printer_q = PrinterQueue(host=labelprinter_host)
        self.printer_q.start()

        self.ctx = Context(
            images_dir=images_dir,
            logs_dir=logs_dir,
            baudrate=baudrate,
            bootloader_password=bootloader_password,
            printer=self.printer_q,
            timestamp=make_timestamp(),
        )
        self.ctx.logs_dir.mkdir(parents=True, exist_ok=True)

        # Per-AP cached metadata + last claimed image (for reprint + restart).
        self._metadata: dict[int, dict] = {}
        self._last_claim = {}  # ap_index -> ClaimedImage (set on metadata event)

        self.executor = ThreadPoolExecutor(
            max_workers=len(ap_indices), thread_name_prefix="flash"
        )
        self._futures: dict[int, Future] = {}

        # GUI attaches its log handlers up front so we capture worker logs from
        # the very first message.
        self._gui_handlers: dict[int, GuiHandler] = {}
        for i in ap_indices:
            log = logging.getLogger(f"autoflash.ap{i}")
            log.setLevel(logging.DEBUG)
            log.propagate = False
            h = GuiHandler(i, self.events)
            log.addHandler(h)
            self._gui_handlers[i] = h

        self._build_window()

    # -- window layout --

    def _build_window(self):
        self.root = tk.Tk()
        self.root.title("Huawei AP Parallel Flasher")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        topbar = tk.Frame(self.root, padx=6, pady=4)
        topbar.pack(fill=tk.X)
        n = len(self.ap_indices)
        tk.Label(
            topbar,
            text=f"{n} APs - images: {self.ctx.images_dir} - "
            f"logs: {self.ctx.logs_dir} - "
            f"printer: {self.printer_q.host or '(none)'}",
        ).pack(side=tk.LEFT)
        self.btn_start = tk.Button(topbar, text="Start", command=self._on_start)
        self.btn_start.pack(side=tk.RIGHT)

        # Grid of panels: prefer 4 columns wide.
        cols = min(4, len(self.ap_indices))
        rows = math.ceil(len(self.ap_indices) / cols)
        grid = tk.Frame(self.root, padx=6, pady=4)
        grid.pack(fill=tk.BOTH, expand=True)
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="panels")
        for r in range(rows):
            grid.grid_rowconfigure(r, weight=1, uniform="panels")

        self.panels: dict[int, APPanel] = {}
        for idx, ap in enumerate(self.ap_indices):
            r, c = divmod(idx, cols)
            p = APPanel(
                grid,
                ap_index=ap,
                on_reprint_wifi=self._on_reprint_wifi,
                on_reprint_login=self._on_reprint_login,
                on_restart=self._on_restart,
            )
            p.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
            self.panels[ap] = p

        self.status_var = tk.StringVar(value="Idle")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padx=6,
        ).pack(fill=tk.X, side=tk.BOTTOM)

    # -- start/stop flow --

    def _on_start(self):
        self.btn_start.configure(state=tk.DISABLED)
        self.status_var.set("Disabling PoE on used ports...")

        def setup_then_confirm():
            try:
                poe.disable(self.ap_indices)
            except Exception as e:
                self.events.put(("error", f"PoE disable failed: {e}"))
                return
            self.events.put(("ready_to_confirm", None))

        threading.Thread(target=setup_then_confirm, daemon=True).start()

    def _confirm_and_run(self):
        ok = messagebox.askokcancel(
            "Connect APs",
            f"PoE is OFF on ports {self.ap_indices}.\n\n"
            "Connect the APs to the corresponding switch ports and serial "
            "adapters, then click OK to start flashing.",
        )
        if not ok:
            self.btn_start.configure(state=tk.NORMAL)
            self.status_var.set("Cancelled")
            return
        self.status_var.set("Flashing...")
        for i in self.ap_indices:
            self._submit(i)

    def _submit(self, ap_index: int):
        self.panels[ap_index].set_state("running", "starting")
        self.panels[ap_index].disable_buttons_during_run()
        fut = self.executor.submit(flash_one, ap_index, self.ctx, self._status_cb)
        self._futures[ap_index] = fut
        fut.add_done_callback(
            lambda f, i=ap_index: self.events.put(
                WorkerFinished(ap=i, ok=(f.exception() is None and f.result()))
            )
        )

    def _status_cb(self, ap, event, **fields):
        self.events.put(StatusEvent(ap=ap, event=event, fields=fields))

    # -- button handlers --

    def _on_reprint_wifi(self, ap_index: int):
        md = self._metadata.get(ap_index)
        if md:
            self.printer_q.print_wifi(md)
            self.status_var.set(f"Re-queued WiFi label for ap{ap_index}")

    def _on_reprint_login(self, ap_index: int):
        md = self._metadata.get(ap_index)
        if md:
            self.printer_q.print_login(md, self.ctx.bootloader_password)
            self.status_var.set(f"Re-queued login label for ap{ap_index}")

    def _on_restart(self, ap_index: int):
        # Reuse last claim if we still have valid file paths for this slot
        # (i.e. the previous run succeeded). On failure the cache was
        # cleared, so the worker will atomically claim a fresh image.
        claim = self._last_claim.get(ap_index)
        if claim is not None:
            with self.ctx.reuse_lock:
                self.ctx.reuse[ap_index] = claim
        self._submit(ap_index)

    # -- event drain --

    def _drain(self):
        try:
            while True:
                ev = self.events.get_nowait()
                self._dispatch(ev)
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _dispatch(self, ev):
        if isinstance(ev, LogLine):
            p = self.panels.get(ev.ap)
            if p:
                p.append_log(ev.level, ev.message)
        elif isinstance(ev, StatusEvent):
            p = self.panels.get(ev.ap)
            if not p:
                return
            if ev.event == "metadata":
                md = ev.fields.get("metadata", {})
                claim = ev.fields.get("claim")
                self._metadata[ev.ap] = md
                if claim is not None:
                    self._last_claim[ev.ap] = claim
                p.set_metadata(md)
            elif ev.event in ("flashing", "poe_on", "poe_off", "started"):
                p.set_state("running", ev.event)
            elif ev.event == "done":
                p.set_state("done", "")
            elif ev.event == "failed":
                # On failure the orchestrator restored the image back to the
                # pool, so the cached ClaimedImage is stale - drop it so a
                # Restart picks a fresh image.
                self._last_claim.pop(ev.ap, None)
                p.set_state("failed", ev.fields.get("error", ""))
        elif isinstance(ev, WorkerFinished):
            p = self.panels.get(ev.ap)
            if p:
                p.enable_restart()
            if all(f.done() for f in self._futures.values()):
                self.status_var.set("All workers finished")
        elif isinstance(ev, tuple) and ev[0] == "ready_to_confirm":
            self._confirm_and_run()
        elif isinstance(ev, tuple) and ev[0] == "error":
            messagebox.showerror("Error", ev[1])
            self.status_var.set(ev[1])

    # -- shutdown --

    def _on_close(self):
        if any(not f.done() for f in self._futures.values()):
            if not messagebox.askyesno(
                "Quit", "Workers are still running. Quit anyway?"
            ):
                return
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        finally:
            self.printer_q.stop(drain=False)
            self.root.destroy()

    def run(self):
        self.root.after(50, self._drain)
        self.root.mainloop()
