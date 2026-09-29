"""The scheduler panel: queue and RunEngine controls, the queue, and the run history.

Laid out like ScriptRunner's scheduler (controls on top, a table on the left and
the selected task's details on the right), but the table is the server's queue.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from planrunner.controllers.queue import HistoryRow, QueueHandlers, QueueRow
from planrunner.status_text import Controls
from planrunner.ui.style import ERROR_FG, RUNNING_BG
from planrunner.ui.widgets import ReadOnlyText, set_enabled


class SchedulerPanel:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = ttk.LabelFrame(parent, text="Scheduler", padding=0)
        self._buttons: dict[str, ttk.Button] = {}
        self._loop = tk.BooleanVar()
        self._build_controls()

        notebook = ttk.Notebook(self.frame)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._queue_tree, self._queue_details = self._build_queue_tab(notebook)
        self._history_tree, self._history_details = self._build_history_tab(notebook)

    # --- Layout -----------------------------------------------------------------

    def _build_controls(self) -> None:
        bar = ttk.Frame(self.frame)
        bar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        def button(key: str, text: str) -> None:
            self._buttons[key] = ttk.Button(bar, text=text)
            self._buttons[key].pack(side=tk.LEFT, padx=(0, 5))

        def separator() -> None:
            ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(bar, text="Queue:").pack(side=tk.LEFT, padx=(0, 5))
        button("start", "Start")
        button("stop_after_current", "Stop after current")
        button("cancel_stop", "Cancel stop")
        separator()
        ttk.Label(bar, text="Run:").pack(side=tk.LEFT, padx=(0, 5))
        button("pause", "Pause")
        button("pause_now", "Pause now")
        button("resume", "Resume")
        button("stop_run", "Stop")
        button("abort", "Abort")
        button("halt", "Halt")
        separator()
        self._loop_check = ttk.Checkbutton(bar, text="Loop queue", variable=self._loop)
        self._loop_check.pack(side=tk.LEFT, padx=(0, 5))
        button("clear", "Clear queue")

    def _build_queue_tab(self, notebook: ttk.Notebook) -> tuple[ttk.Treeview, ReadOnlyText]:
        pane = ttk.PanedWindow(notebook, orient=tk.HORIZONTAL)
        notebook.add(pane, text="  Queue  ")
        table, tree = _table(pane, {"#": 40, "Plan": 160, "Parameters": 380, "User": 90})
        tree.tag_configure("running", background=RUNNING_BG, font=("", 0, "bold"))

        details = ttk.Frame(pane)
        text = ReadOnlyText(details)
        text.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        row = ttk.Frame(details)
        row.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        for key, label in [("move_up", "▲ Up"), ("move_down", "▼ Down"), ("edit", "Edit"),
                           ("duplicate", "Duplicate"), ("delete", "Delete")]:
            self._buttons[key] = ttk.Button(row, text=label, style="Small.TButton")
            self._buttons[key].pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        pane.add(table, weight=3)
        pane.add(details, weight=2)
        return tree, text

    def _build_history_tab(self, notebook: ttk.Notebook) -> tuple[ttk.Treeview, ReadOnlyText]:
        pane = ttk.PanedWindow(notebook, orient=tk.HORIZONTAL)
        notebook.add(pane, text="  History  ")
        table, tree = _table(
            pane, {"Plan": 160, "Parameters": 300, "Result": 150, "Finished": 80}
        )
        tree.tag_configure("failed", foreground=ERROR_FG)

        details = ttk.Frame(pane)
        text = ReadOnlyText(details)
        text.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._buttons["requeue"] = ttk.Button(details, text="Add to queue again",
                                              style="Small.TButton")
        self._buttons["requeue"].pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

        pane.add(table, weight=3)
        pane.add(details, weight=2)
        return tree, text

    # --- QueueView --------------------------------------------------------------

    def set_handlers(self, handlers: QueueHandlers) -> None:
        commands = {
            "start": handlers.on_start,
            "stop_after_current": handlers.on_stop_after_current,
            "cancel_stop": handlers.on_cancel_stop,
            "pause": lambda: handlers.on_pause(immediate=False),
            "pause_now": lambda: handlers.on_pause(immediate=True),
            "resume": handlers.on_resume,
            "stop_run": handlers.on_stop_run,
            "abort": handlers.on_abort,
            "halt": handlers.on_halt,
            "clear": handlers.on_clear,
            "move_up": lambda: self._with_selected(lambda uid: handlers.on_move(uid, -1)),
            "move_down": lambda: self._with_selected(lambda uid: handlers.on_move(uid, 1)),
            "edit": lambda: self._with_selected(handlers.on_edit),
            "duplicate": lambda: self._with_selected(handlers.on_duplicate),
            "delete": lambda: self._with_selected(handlers.on_delete),
            "requeue": lambda: self._with_history(handlers.on_requeue),
        }
        for key, command in commands.items():
            self._buttons[key].configure(command=command)
        self._loop_check.configure(command=lambda: handlers.on_loop_changed(self._loop.get()))
        self._queue_tree.bind("<<TreeviewSelect>>",
                              lambda _: handlers.on_item_selected(self._selected_uid()))
        self._queue_tree.bind("<Double-Button-1>",
                              lambda _: self._with_selected(handlers.on_edit))
        self._history_tree.bind("<<TreeviewSelect>>",
                                lambda _: handlers.on_history_selected(self._selected_history()))

    def show_queue(self, rows: list[QueueRow]) -> None:
        selected = self._selected_uid()
        _refill(self._queue_tree, [
            (row.uid or f"running-{i}", (row.position, row.title, row.parameters, row.user),
             ("running",) if row.running else ())
            for i, row in enumerate(rows)
        ])
        if selected and self._queue_tree.exists(selected):
            self._queue_tree.selection_set(selected)
        else:
            self._queue_details.set("")

    def show_history(self, rows: list[HistoryRow]) -> None:
        _refill(self._history_tree, [
            (str(row.index), (row.title, row.parameters, row.result, row.finished),
             ("failed",) if row.failed else ())
            for row in rows
        ])
        self._history_details.set("")

    def show_item_details(self, text: str) -> None:
        self._queue_details.set(text)

    def show_history_details(self, text: str) -> None:
        self._history_details.set(text)

    def enable_controls(self, controls: Controls, has_queue: bool) -> None:
        enabled = {
            "start": controls.start,
            "stop_after_current": controls.stop_after_current,
            "cancel_stop": controls.cancel_stop,
            "pause": controls.pause,
            "pause_now": controls.pause,
            "resume": controls.resume,
            "stop_run": controls.stop_run,
            "abort": controls.abort,
            "halt": controls.halt,
            "clear": controls.edit_queue and has_queue,
            "move_up": controls.edit_queue,
            "move_down": controls.edit_queue,
            "edit": controls.edit_queue,
            "duplicate": controls.edit_queue,
            "delete": controls.edit_queue,
            "requeue": controls.edit_queue,
        }
        for key, on in enabled.items():
            set_enabled(self._buttons[key], on)
        set_enabled(self._loop_check, controls.set_loop)

    def show_loop(self, loop: bool) -> None:
        self._loop.set(loop)

    # --- Selection helpers ------------------------------------------------------

    def _selected_uid(self) -> str | None:
        selection = self._queue_tree.selection()
        return selection[0] if selection else None

    def _selected_history(self) -> int | None:
        selection = self._history_tree.selection()
        return int(selection[0]) if selection else None

    def _with_selected(self, action: Callable[[str], None]) -> None:
        if (uid := self._selected_uid()) is not None:
            action(uid)

    def _with_history(self, action: Callable[[int], None]) -> None:
        if (index := self._selected_history()) is not None:
            action(index)


def _table(parent: tk.Misc, columns: dict[str, int]) -> tuple[ttk.Frame, ttk.Treeview]:
    """A scrolled table; returns the frame to place and the tree inside it."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=list(columns), show="headings", selectmode="browse",
                        height=6)
    for name, width in columns.items():
        tree.heading(name, text=name, anchor="w")
        tree.column(name, width=width, stretch=name == "Parameters", anchor="w")
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    return frame, tree


def _refill(tree: ttk.Treeview, rows: list[tuple[str, tuple, tuple]]) -> None:
    tree.delete(*tree.get_children())
    for iid, values, tags in rows:
        tree.insert("", tk.END, iid=iid, values=values, tags=tags)
