"""Left panel: the plans the server allows, with a filter box.

Takes the place of ScriptRunner's "Available scripts" list.
"""

import tkinter as tk
from tkinter import ttk

from planrunner.controllers.plans import PlansHandlers
from planrunner.ui.style import LIST_SELECT_BG, LIST_SELECT_FG


class PlanList:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.LabelFrame(parent, text="   Available plans", padding=0)
        self._filter = tk.StringVar()
        filter_row = ttk.Frame(self.frame)
        filter_row.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(filter_row, text="Filter:").pack(side=tk.LEFT)
        ttk.Entry(filter_row, textvariable=self._filter).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0)
        )

        self._list = tk.Listbox(
            self.frame,
            selectmode=tk.SINGLE,
            bd=0,
            highlightthickness=1,
            relief="solid",
            exportselection=False,
            selectbackground=LIST_SELECT_BG,
            selectforeground=LIST_SELECT_FG,
            activestyle="none",
        )
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self._list.yview)
        self._list.configure(yscrollcommand=scrollbar.set)
        self._list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        self._names: list[str] = []

    def set_handlers(self, handlers: PlansHandlers) -> None:
        self._filter.trace_add("write", lambda *_: handlers.on_filter_changed(self._filter.get()))
        self._list.bind("<<ListboxSelect>>", lambda _: self._selected(handlers))

    def show_plans(self, names: list[str], selected: str | None) -> None:
        self._names = list(names)
        self._list.delete(0, tk.END)
        for name in names:
            self._list.insert(tk.END, name)
        if selected in self._names:
            index = self._names.index(selected)
            self._list.selection_set(index)
            self._list.see(index)

    def _selected(self, handlers: PlansHandlers) -> None:
        if selection := self._list.curselection():
            handlers.on_plan_selected(self._names[selection[0]])
