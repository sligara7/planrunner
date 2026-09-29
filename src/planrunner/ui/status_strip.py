"""The status strip under the connection bar: RE Manager state at a glance."""

import tkinter as tk
from tkinter import ttk

from planrunner.status_text import StatusField


class StatusStrip:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.Frame(parent, padding=(5, 2))
        self._labels: list[tuple[ttk.Label, ttk.Label]] = []

    def show_fields(self, fields: list[StatusField]) -> None:
        while len(self._labels) < len(fields):
            name = ttk.Label(self.frame, style="StatusName.TLabel")
            value = ttk.Label(self.frame)
            name.pack(side=tk.LEFT, padx=(10, 2))
            value.pack(side=tk.LEFT, padx=(0, 10))
            self._labels.append((name, value))
        for i, (name, value) in enumerate(self._labels):
            if i < len(fields):
                field = fields[i]
                name.configure(text=f"{field.label}:")
                value.configure(text=field.value, style=f"{field.tone.value}.Status.TLabel")
            else:
                name.configure(text="")
                value.configure(text="")
