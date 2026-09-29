"""Bottom panel: RE worker console output and GUI notices, with save-to-log-file.

Same layout as ScriptRunner's console.
"""

import tkinter as tk
from tkinter import ttk

from planrunner.controllers.console import ConsoleHandlers
from planrunner.ui.style import ACCENT, BG_OUTPUT, CONSOLE_FONT, ERROR_FG, FG_OUTPUT
from planrunner.ui.widgets import set_enabled

MAX_LINES = 5000


class ConsolePanel:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.Frame(parent)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        options = ttk.Frame(self.frame, padding=(5, 5, 0, 2))
        options.grid(row=0, column=0, sticky="ew")
        options.grid_columnconfigure(1, weight=1)
        self._log_enabled = tk.BooleanVar()
        self._log_check = ttk.Checkbutton(
            options, text="Console output | Save to log file: ", variable=self._log_enabled
        )
        self._log_check.grid(row=0, column=0, sticky="w")
        self._log_path = ttk.Label(options, style="Path.TLabel", anchor="w")
        self._log_path.grid(row=0, column=1, sticky="ew", padx=5)
        self._choose = ttk.Button(options, text="Select file", style="Small.TButton")
        self._choose.grid(row=0, column=2)
        self._clear = ttk.Button(options, text="Clear", style="Small.TButton")
        self._clear.grid(row=0, column=3, padx=5)

        box = ttk.Frame(self.frame)
        box.grid(row=1, column=0, sticky="nsew", padx=5, pady=(2, 5))
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)
        self._text = tk.Text(box, height=10, state=tk.DISABLED, bg=BG_OUTPUT, fg=FG_OUTPUT,
                             font=CONSOLE_FONT, bd=0, highlightthickness=0)
        self._text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=self._text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.tag_configure("output", foreground=FG_OUTPUT)
        self._text.tag_configure("info", foreground=ACCENT)
        self._text.tag_configure("error", foreground=ERROR_FG)

    def set_handlers(self, handlers: ConsoleHandlers) -> None:
        self._log_check.configure(
            command=lambda: handlers.on_log_toggled(self._log_enabled.get())
        )
        self._choose.configure(command=handlers.on_choose_log_file)
        self._clear.configure(command=handlers.on_clear)

    def append(self, text: str, tag: str) -> None:
        at_bottom = self._text.yview()[1] >= 0.999
        self._text.configure(state=tk.NORMAL)
        self._text.insert(tk.END, text, tag)
        excess = int(self._text.index("end-1c").split(".")[0]) - MAX_LINES
        if excess > 0:
            self._text.delete("1.0", f"{excess + 1}.0")
        self._text.configure(state=tk.DISABLED)
        if at_bottom:
            self._text.see(tk.END)

    def clear(self) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)

    def show_log_file(self, path: str | None, enabled: bool) -> None:
        self._log_enabled.set(enabled)
        self._log_path.configure(text=path or "No log file selected",
                                 foreground=ACCENT if enabled else "#888")
        set_enabled(self._choose, True)
