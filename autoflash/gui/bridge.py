"""Bridge between Python logging and the GUI event queue.

Each worker thread attaches a GuiHandler bound to its AP index. Records flow
into the shared event queue; the GUI mainloop drains and routes them to the
matching panel's text widget.
"""

from __future__ import annotations

import logging
import queue

from .events import LogLine


class GuiHandler(logging.Handler):
    def __init__(self, ap_index: int, q: queue.Queue):
        super().__init__()
        self.ap_index = ap_index
        self._q = q
        self.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._q.put(LogLine(ap=self.ap_index, level=record.levelno, message=msg))
