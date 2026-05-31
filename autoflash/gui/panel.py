"""Single-AP panel widget."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import Callable


_LEVEL_COLOR = {
    "DEBUG": "#888888",
    "INFO": "#000000",
    "WARNING": "#a06000",
    "ERROR": "#c00000",
    "CRITICAL": "#c00000",
}


_STATE_COLOR = {
    "idle": "#888888",
    "running": "#0060c0",
    "done": "#008040",
    "failed": "#c00000",
}


class APPanel(tk.LabelFrame):
    def __init__(
        self,
        master,
        ap_index: int,
        on_reprint_wifi: Callable[[int], None],
        on_reprint_login: Callable[[int], None],
        on_restart: Callable[[int], None],
    ):
        super().__init__(
            master,
            text=f"AP {ap_index}  -  /dev/ttyUSB{ap_index}  -  ge-0/0/{ap_index}",
            padx=4,
            pady=4,
        )
        self.ap_index = ap_index
        self.has_metadata = False

        header = tk.Frame(self)
        header.pack(fill=tk.X)

        self.state_var = tk.StringVar(value="idle")
        self.state_label = tk.Label(
            header,
            textvariable=self.state_var,
            fg=_STATE_COLOR["idle"],
            font=("TkDefaultFont", 10, "bold"),
        )
        self.state_label.pack(side=tk.LEFT)

        self.step_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.step_var).pack(side=tk.LEFT, padx=(8, 0))

        self.meta_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.meta_var, fg="#404040").pack(side=tk.RIGHT)

        self.log = scrolledtext.ScrolledText(
            self,
            height=10,
            width=60,
            font=("DejaVu Sans Mono", 9),
            state=tk.DISABLED,
            wrap=tk.NONE,
        )
        self.log.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        for level, color in _LEVEL_COLOR.items():
            self.log.tag_configure(level, foreground=color)

        btnbar = tk.Frame(self)
        btnbar.pack(fill=tk.X)
        self.btn_wifi = tk.Button(
            btnbar,
            text="Print WiFi label",
            state=tk.DISABLED,
            command=lambda: on_reprint_wifi(self.ap_index),
        )
        self.btn_wifi.pack(side=tk.LEFT)
        self.btn_login = tk.Button(
            btnbar,
            text="Print Login label",
            state=tk.DISABLED,
            command=lambda: on_reprint_login(self.ap_index),
        )
        self.btn_login.pack(side=tk.LEFT, padx=(4, 0))
        self.btn_both = tk.Button(
            btnbar,
            text="Print both",
            state=tk.DISABLED,
            command=lambda: (on_reprint_wifi(self.ap_index), on_reprint_login(self.ap_index)),
        )
        self.btn_both.pack(side=tk.LEFT, padx=(4, 0))
        self.btn_restart = tk.Button(
            btnbar,
            text="Restart this AP",
            state=tk.DISABLED,
            command=lambda: on_restart(self.ap_index),
        )
        self.btn_restart.pack(side=tk.LEFT, padx=(4, 0))

    # -- updates from main thread (called by App.drain_events) --

    def append_log(self, level: int, msg: str):
        import logging

        name = logging.getLevelName(level)
        tag = name if name in _LEVEL_COLOR else "INFO"
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n", tag)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def set_state(self, state: str, step: str = ""):
        self.state_var.set(state)
        self.step_var.set(step)
        self.state_label.configure(fg=_STATE_COLOR.get(state, "#000000"))

    def set_metadata(self, metadata: dict):
        self.meta_var.set(f"SSID: {metadata.get('ssid', '?')}")
        self.has_metadata = True
        self.btn_wifi.configure(state=tk.NORMAL)
        self.btn_login.configure(state=tk.NORMAL)
        self.btn_both.configure(state=tk.NORMAL)

    def set_metadata_cleared(self):
        self.meta_var.set("")
        self.has_metadata = False
        self.btn_wifi.configure(state=tk.DISABLED)
        self.btn_login.configure(state=tk.DISABLED)
        self.btn_both.configure(state=tk.DISABLED)
        self.btn_restart.configure(state=tk.DISABLED)

    def enable_restart(self):
        if self.has_metadata:
            self.btn_restart.configure(state=tk.NORMAL)

    def clear_log(self):
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def disable_buttons_during_run(self):
        self.btn_restart.configure(state=tk.DISABLED)
