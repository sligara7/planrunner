"""Tk implementations of the small UI services controllers depend on."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from planrunner.dispatch import QueueDispatcher


class TkDialogs:
    """``planrunner.protocols.Dialogs`` using tkinter's standard dialogs."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root

    def confirm(self, title: str, message: str) -> bool:
        return messagebox.askyesno(title, message, parent=self._root)

    def error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self._root)

    def ask_save_path(self, title: str, initial_file: str) -> str | None:
        path = filedialog.asksaveasfilename(
            parent=self._root,
            title=title,
            initialdir=str(Path.home()),
            initialfile=initial_file,
            defaultextension=".txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        return path or None


class StatusBar:
    """``planrunner.protocols.StatusLine``: the sunken one-line bar at the bottom."""

    def __init__(self, parent: tk.Misc) -> None:
        self._var = tk.StringVar()
        self.frame = ttk.Label(parent, textvariable=self._var, relief=tk.SUNKEN, anchor="w",
                               padding=(5, 2))

    def set_message(self, text: str) -> None:
        self._var.set(text)


class TkPump:
    """Drains a ``QueueDispatcher`` on the Tk event loop, every ``interval_ms``."""

    def __init__(self, root: tk.Misc, dispatcher: QueueDispatcher, interval_ms: int = 50) -> None:
        self._root = root
        self._dispatcher = dispatcher
        self._interval_ms = interval_ms
        self._job: str | None = None

    def start(self) -> None:
        self._dispatcher.drain()
        self._job = self._root.after(self._interval_ms, self.start)

    def stop(self) -> None:
        if self._job is not None:
            self._root.after_cancel(self._job)
            self._job = None
