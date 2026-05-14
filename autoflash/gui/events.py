"""Events posted from worker threads to the GUI mainloop via queue.Queue.

The GUI drains the queue on a Tk timer (`root.after`) and dispatches each
event to the matching AP panel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LogLine:
    ap: int
    level: int
    message: str


@dataclass
class StatusEvent:
    ap: int
    event: str  # "started" | "metadata" | "poe_on" | "flashing"
    # | "poe_off" | "done" | "failed"
    fields: dict


@dataclass
class WorkerFinished:
    ap: int
    ok: bool
