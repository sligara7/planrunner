"""The main window: builds each panel and lays them out the way ScriptRunner does.

    row 0  connection bar
    row 1  status strip
    row 2  plan list | plan parameters
    row 3  ── ▲ Hide scheduler ──
    row 4  scheduler (queue, history, controls)
    row 5  console
    row 6  status bar
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from planrunner.ui.connection_bar import ConnectionBar
from planrunner.ui.console_panel import ConsolePanel
from planrunner.ui.plan_form import PlanForm
from planrunner.ui.plan_list import PlanList
from planrunner.ui.scheduler import SchedulerPanel
from planrunner.ui.services import StatusBar
from planrunner.ui.status_strip import StatusStrip
from planrunner.ui.style import MAIN_WINDOW_RATIO, apply_style

_SCHEDULER_ROW = 4
_CONSOLE_ROW = 5


class MainWindow:
    def __init__(self, title: str = "Plan Runner", root: tk.Tk | None = None) -> None:
        self.root = root or tk.Tk()
        self.root.title(title)
        apply_style(self.root)
        self._fit_to_screen()

        self.connection_bar = ConnectionBar(self.root)
        self.status_strip = StatusStrip(self.root)
        middle = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.plan_list = PlanList(middle)
        self.plan_form = PlanForm(middle)
        middle.add(self.plan_list.frame, weight=1)
        middle.add(self.plan_form.frame, weight=3)
        toggle_row = ttk.Frame(self.root)
        self.scheduler = SchedulerPanel(self.root)
        self.console = ConsolePanel(self.root)
        self.status_bar = StatusBar(self.root)

        self.connection_bar.frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(0, 5))
        self.status_strip.frame.grid(row=1, column=0, sticky="ew", padx=5)
        middle.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        toggle_row.grid(row=3, column=0, sticky="ew", padx=5)
        self.scheduler.frame.grid(row=_SCHEDULER_ROW, column=0, sticky="nsew", padx=5, pady=(5, 0))
        self.console.frame.grid(row=_CONSOLE_ROW, column=0, sticky="nsew", padx=5, pady=5)
        self.status_bar.frame.grid(row=6, column=0, sticky="ew", padx=5, pady=(0, 5))

        self._toggle = ttk.Button(toggle_row, style="Toggle.TButton", width=20,
                                  command=self.toggle_scheduler)
        ttk.Separator(toggle_row).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._toggle.pack(side=tk.LEFT, padx=10)
        ttk.Separator(toggle_row).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=5)
        self._scheduler_visible = False
        self.toggle_scheduler()  # the queue is central here, so start with it shown

    def toggle_scheduler(self) -> None:
        self._scheduler_visible = not self._scheduler_visible
        if self._scheduler_visible:
            self.scheduler.frame.grid()
            self._toggle.configure(text="▲ Hide scheduler")
            self.root.grid_rowconfigure(_SCHEDULER_ROW, weight=4)
        else:
            self.scheduler.frame.grid_remove()
            self._toggle.configure(text="▼ Show scheduler")
            self.root.grid_rowconfigure(_SCHEDULER_ROW, weight=0)
        self.root.grid_rowconfigure(_CONSOLE_ROW, weight=2)

    def on_close(self, callback: Callable[[], None]) -> None:
        self.root.protocol("WM_DELETE_WINDOW", callback)

    def _fit_to_screen(self) -> None:
        width = int(self.root.winfo_screenwidth() * MAIN_WINDOW_RATIO)
        height = int(self.root.winfo_screenheight() * MAIN_WINDOW_RATIO)
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
