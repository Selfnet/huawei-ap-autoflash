"""Junos PoE control over SSH for the EX4100-F switch.

Wraps `cli -c "configure; ...; commit"` with a module-level lock so concurrent
callers (one per parallel flash worker) do not stomp on each other's commits.
Junos commits from independent sessions can also collide; serializing here is
simpler than batching.
"""

from __future__ import annotations

import logging
import subprocess
import threading


SWITCH_HOST = "root@192.168.0.1"
SSH_BASE = ["ssh", "-o", "BatchMode=yes", SWITCH_HOST]

_lock = threading.Lock()
_log = logging.getLogger(__name__)


def _iface(port: int) -> str:
    return f"ge-0/0/{port}"


def _ssh_cli(cmd: str) -> str:
    result = subprocess.run(
        SSH_BASE + [f'cli -c "{cmd}"'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Junos SSH error: {result.stderr.strip()}")
    return result.stdout


def disable(ports: list[int]):
    if not ports:
        return
    ifaces = [_iface(p) for p in ports]
    sets = "; ".join(f"set poe interface {i} disable" for i in ifaces)
    with _lock:
        _log.info("Disabling PoE on %s", ", ".join(ifaces))
        _ssh_cli(f"configure; {sets}; commit")


def enable(ports: list[int]):
    if not ports:
        return
    ifaces = [_iface(p) for p in ports]
    deletes = "; ".join(f"delete poe interface {i} disable" for i in ifaces)
    with _lock:
        _log.info("Enabling PoE on %s", ", ".join(ifaces))
        _ssh_cli(f"configure; {deletes}; commit")


def disable_one(port: int):
    disable([port])


def enable_one(port: int):
    enable([port])
