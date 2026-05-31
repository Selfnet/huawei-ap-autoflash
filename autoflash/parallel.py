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

import json
import logging
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import TFTP_IP, run_autoflash, images, poe
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
    success = False
    claimed: images.ClaimedImage | None = None
    reused = False
    try:
        status(ap_index, "started")
        # Reuse-or-claim
        with ctx.reuse_lock:
            claimed = ctx.reuse.pop(ap_index, None)
        if claimed is not None:
            reused = True
            log.info("Reusing previously-claimed image %s", claimed.metadata.name)
        else:
            tmp = Path(tempfile.mkdtemp(prefix=f"ap{ap_index}-"))
            claimed = images.claim(ctx.images_dir, tmp)
            log.info("Claimed image %s", claimed.metadata.name)

        metadata = json.loads(claimed.metadata.read_text())
        status(ap_index, "metadata", metadata=metadata, claim=claimed)

        # Print labels (no-op if printer host is None). Skip on reuse so we
        # don't spit out duplicate labels for the same AP.
        if not reused:
            ctx.printer.print_wifi(metadata)
            ctx.printer.print_login(metadata, ctx.bootloader_password)

        status(ap_index, "poe_on")
        poe.enable_one(ap_index)
        poe_enabled = True

        ap_ip = get_free_ip(reserved_ips=[TFTP_IP])
        status(ap_index, "flashing", ap_ip=str(ap_ip))
        run_autoflash(
            ramboot_file_name="ramboot.bin",
            sysupgrade_path=str(claimed.sysupgrade),
            port=serial_port,
            speed=ctx.baudrate,
            password=ctx.bootloader_password,
            ap_ip=ap_ip,
            logger=log,
        )

        time.sleep(5)
        status(ap_index, "done")
        # Successful flash: keep files in the worker's tmpdir so the GUI can
        # reuse the same ClaimedImage if the user clicks "Restart this AP"
        # (e.g. they want to re-image the same AP after a re-seat). The OS
        # cleans /tmp on next boot; the disk cost is small (~10 MB per slot).
        success = True
        return True

    except Exception as e:
        log.exception("flash failed")
        if claimed is not None:
            try:
                claimed.restore()
                log.info("Restored image %s to pool", claimed.metadata.name)
            except Exception:
                log.exception("failed to restore image")
        status(ap_index, "failed", error=repr(e))
        return False

    finally:
        if poe_enabled and not ctx.keep_poe_on:
            try:
                poe.disable_one(ap_index)
                status(ap_index, "poe_off")
            except Exception:
                log.exception("failed to disable PoE")
        elif poe_enabled and ctx.keep_poe_on:
            log.info(
                "Leaving PoE enabled (keep_poe_on, %s)",
                "success" if success else "failure - useful for debugging",
            )
            status(ap_index, "poe_kept")
        log.removeHandler(fh)
        fh.close()


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
