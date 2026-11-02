"""Headless parallel-flash orchestrator.

Spawns one worker thread per AP index. Each worker:
  1. opens its per-AP log file
  2. atomically claims an image pair from the shared images dir
  3. enqueues label prints
  4. enables PoE on its switch port
  5. runs the existing single-AP flash flow
  6. disables PoE (always, even on failure)
  7. on flash failure, restores the image to the pool

Workers share: image pool dir, IP allocator (already locked), printer queue
(single thread), PoE controller (lock around SSH+commit). Status events are
emitted via an optional callback so a GUI (or CLI driver) can react.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import OPENWRT_DEFAULT_LAN_IP, TFTP_IP, run_autoflash, images, poe
from .history import FlashHistory
from .ips import get_free_ip
from .printer_queue import PrinterQueue


@dataclass
class Context:
    images_dir: Path
    logs_dir: Path
    baudrate: int
    bootloader_password: str
    printer: PrinterQueue
    timestamp: str
    old_uboot_passwords: list[str] | None = None
    # If True, leave PoE enabled on a slot after the worker exits regardless
    # of outcome. On success this lets the newly-flashed AP keep running for
    # verification; on failure it lets the user inspect the half-flashed AP
    # via serial / network for debugging. Toggleable from the GUI.
    keep_poe_on: bool = False
    # Reuse-image map for "Restart this AP": ap_index -> ClaimedImage that the
    # worker should reuse instead of claiming a new one. Populated by the GUI
    # when the user clicks Restart; the worker pops its entry on start.
    reuse: dict[int, images.ClaimedImage] = field(default_factory=dict)
    reuse_lock: threading.Lock = field(default_factory=threading.Lock)
    cancel_events: dict[int, threading.Event] = field(default_factory=dict)
    history_db: Path = Path("flash-history.sqlite")
    history: FlashHistory = field(init=False)

    def __post_init__(self):
        self.history = FlashHistory(self.history_db)


# Status callback signature: (ap_index, event_name, **fields)
StatusCb = Callable[..., None]


def _noop_cb(*_a, **_kw):
    pass


def _setup_ap_logger(
    ap_index: int, ctx: Context
) -> tuple[logging.Logger, logging.Handler]:
    log = logging.getLogger(f"autoflash.ap{ap_index}")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    fh = logging.FileHandler(ctx.logs_dir / f"ap{ap_index}-{ctx.timestamp}.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    log.addHandler(fh)
    return log, fh


def flash_one(
    ap_index: int,
    ctx: Context,
    status: StatusCb = _noop_cb,
) -> bool:
    """Flash a single AP. Returns True on success, False on failure."""
    log, fh = _setup_ap_logger(ap_index, ctx)
    serial_port = f"/dev/ttyUSB{ap_index}"
    poe_enabled = False
    poe_state = "unknown"
    success = False
    claimed: images.ClaimedImage | None = None
    cancel_event = threading.Event()
    ctx.cancel_events[ap_index] = cancel_event
    attempt_id = None
    outcome = "interrupted"
    error = None
    network = {}

    def record(event, *, changes=None, **details):
        ctx.history.record(attempt_id, event, changes=changes, **details)

    def record_cleanup(event, **details):
        if attempt_id is not None:
            try:
                record(event, **details)
            except Exception:
                log.exception("failed to update flash history during cleanup")

    def progress(event, **details):
        changes = {"stage": event}
        if event == "network":
            network[details["phase"]] = details["interfaces"]
            changes = {"network_json": json.dumps(network)}
        elif event == "network_unavailable":
            changes = {}
        record(event, changes=changes, **details)

    try:
        attempt_id = ctx.history.start(
            batch_id=ctx.timestamp,
            ap_index=ap_index,
            serial_port=serial_port,
            baudrate=ctx.baudrate,
            switch_host=poe.SWITCH_HOST,
            switch_port=f"ge-0/0/{ap_index}",
            images_dir=str(ctx.images_dir.resolve()),
            log_path=str((ctx.logs_dir / f"ap{ap_index}-{ctx.timestamp}.log").resolve()),
            ramboot_image="ramboot.bin",
            tftp_ip=str(TFTP_IP),
            openwrt_default_ip=str(OPENWRT_DEFAULT_LAN_IP),
            config_json=json.dumps({
                "bootloader_password": ctx.bootloader_password,
                "old_uboot_passwords": ctx.old_uboot_passwords,
                "labelprinter_host": ctx.printer.host,
                "keep_poe_on": ctx.keep_poe_on,
            }),
        )
        status(ap_index, "started", attempt_id=attempt_id)
        # Reuse-or-claim
        progress("claiming_image")
        with ctx.reuse_lock:
            claimed = ctx.reuse.pop(ap_index, None)
        reused = claimed is not None
        if claimed is not None:
            log.info("Reusing previously-claimed image %s", claimed.metadata.name)
        else:
            tmp = Path(tempfile.mkdtemp(prefix=f"ap{ap_index}-"))
            claimed = images.claim(ctx.images_dir, tmp)
            log.info("Claimed image %s", claimed.metadata.name)

        record(
            "image_claimed",
            changes={
                "image_name": claimed.sysupgrade.name,
                "image_path": str(claimed.sysupgrade.resolve()),
                "metadata_filename": claimed.original_name,
            },
            reused=reused,
        )
        progress("reading_metadata")
        raw_metadata = claimed.metadata.read_text()
        record("metadata_read", changes={"metadata_raw": raw_metadata})
        metadata = json.loads(raw_metadata)
        record("metadata", changes={"metadata_json": json.dumps(metadata)})
        progress("hashing_image")
        digest = hashlib.sha256()
        with claimed.sysupgrade.open("rb") as image:
            for chunk in iter(lambda: image.read(1024 * 1024), b""):
                digest.update(chunk)
        record(
            "image_identified",
            changes={
                "image_sha256": digest.hexdigest(),
                "image_size_bytes": claimed.sysupgrade.stat().st_size,
            },
        )
        status(ap_index, "metadata", metadata=metadata, claim=claimed)

        progress("enabling_poe")
        status(ap_index, "poe_on")
        poe.enable_one(ap_index)
        poe_enabled = True
        poe_state = "on"
        record("poe_on", changes={"poe_state": "on"})

        ap_ip = get_free_ip(reserved_ips=[TFTP_IP])
        record("ip_allocated", changes={"flash_ip": str(ap_ip)}, flash_ip=str(ap_ip))
        status(ap_index, "flashing", ap_ip=str(ap_ip))
        run_autoflash(
            ramboot_file_name="ramboot.bin",
            sysupgrade_path=str(claimed.sysupgrade),
            port=serial_port,
            speed=ctx.baudrate,
            password=ctx.bootloader_password,
            ap_ip=ap_ip,
            logger=log,
            cancel_event=cancel_event,
            old_uboot_passwords=ctx.old_uboot_passwords,
            progress=progress,
        )

        time.sleep(5)
        # Successful flash: keep files in the worker's tmpdir so the GUI can
        # reuse the same ClaimedImage if the user clicks "Restart this AP"
        # (e.g. they want to re-image the same AP after a re-seat). The OS
        # cleans /tmp on next boot; the disk cost is small (~10 MB per slot).
        success = True
        outcome = "succeeded"

    except Exception as e:
        error = e
        outcome = "aborted" if cancel_event.is_set() else "failed"
        log.exception("flash failed")
        record_cleanup("flash_error", error_type=type(e).__name__, error_message=str(e))
        if claimed is not None and not cancel_event.is_set():
            try:
                claimed.restore()
                log.info("Restored image %s to pool", claimed.metadata.name)
                record_cleanup("image_restored")
            except Exception as restore_error:
                log.exception("failed to restore image")
                record_cleanup(
                    "image_restore_failed",
                    error_type=type(restore_error).__name__,
                    error_message=str(restore_error),
                )
        status(ap_index, "failed", error=repr(e), aborted=cancel_event.is_set())

    except BaseException as e:
        error = e
        raise

    finally:
        try:
            if poe_enabled and not ctx.keep_poe_on:
                try:
                    poe.disable_one(ap_index)
                except Exception as e:
                    poe_state = "unknown"
                    log.exception("failed to disable PoE")
                    record_cleanup(
                        "poe_off_failed",
                        changes={"poe_state": "unknown"},
                        error_type=type(e).__name__,
                        error_message=str(e),
                    )
                else:
                    poe_state = "off"
                    record_cleanup("poe_off", changes={"poe_state": "off"})
                    status(ap_index, "poe_off")
            elif poe_enabled and ctx.keep_poe_on:
                log.info(
                    "Leaving PoE enabled (keep_poe_on, %s)",
                    "success" if success else "failure - useful for debugging",
                )
                record_cleanup("poe_kept", keep_poe_on=True)
                status(ap_index, "poe_kept")
            if attempt_id is not None:
                try:
                    ctx.history.finish(attempt_id, outcome, error, poe_state=poe_state)
                except Exception as e:
                    log.exception("failed to save final flash result")
                    status(
                        ap_index, "failed", error=f"History update failed: {e}", aborted=False
                    )
                    raise
        finally:
            ctx.cancel_events.pop(ap_index, None)
            log.removeHandler(fh)
            fh.close()

    if success:
        status(ap_index, "done")
    return success


def run_parallel(
    ap_indices: list[int],
    ctx: Context,
    status: StatusCb = _noop_cb,
) -> dict[int, bool]:
    """Flash all APs in `ap_indices` concurrently. Returns {ap_index: ok}."""
    ctx.logs_dir.mkdir(parents=True, exist_ok=True)
    # Initial PoE-off on the ports we'll be using.
    poe.disable(ap_indices)

    results: dict[int, bool] = {}
    with ThreadPoolExecutor(max_workers=len(ap_indices)) as pool:
        futures: dict[Future, int] = {
            pool.submit(flash_one, i, ctx, status): i for i in ap_indices
        }
        for fut in futures:
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = False
    return results


def make_timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")
