"""The scheduler: ScriptRunner's scheduler panel.

One control row ("Iteration | Run queue | Pause | Resume | Stop | Clear | Sleep(s) |
Position | Add sleep"), with the queueserver-only controls in a "More" menu; the
"ID | Iter | Name/Details | Status" table; and "Task Details" with Edit / Save / Delete.
"""

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from planrunner.controllers.queue import RowState, SchedulerHandlers, ScheduleRow
from planrunner.plan_params import FormValue, PlanSpec
from planrunner.status_text import Controls
from planrunner.ui.fields import ParamGrid
from planrunner.ui.style import ERROR, RUNNING_BG

_UID = Qt.ItemDataRole.UserRole
_COLUMNS = ("ID", "Iter", "Name/Details", "Status")


class SchedulerPanel:
    def __init__(self, reveal: Callable[[], None]) -> None:
        self._reveal = reveal
        self._handlers: SchedulerHandlers | None = None
        self.widget = QGroupBox("Scheduler")
        layout = QVBoxLayout(self.widget)
        layout.addLayout(self._build_controls())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_details())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    # --- Layout -----------------------------------------------------------------

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._iterations = QSpinBox()
        self._iterations.setRange(1, 999)
        self._run_queue = QPushButton("Run queue")
        self._pause = QPushButton("Pause")
        self._resume = QPushButton("Resume")
        self._stop = QPushButton("Stop")
        self._clear = QPushButton("Clear")
        self._more = QToolButton()
        self._more.setText("More ▾")
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = QMenu(self._more)
        self._actions: dict[str, QAction] = {}
        for key, label in [("pause_now", "Pause now"),
                           ("stop_after_current", "Stop after current plan"),
                           ("cancel_stop", "Cancel stop"), ("-", ""),
                           ("abort", "Abort paused plan"), ("halt", "Halt paused plan"),
                           ("--", ""), ("loop", "Loop queue")]:
            if key.startswith("-"):
                self._menu.addSeparator()
                continue
            self._actions[key] = self._menu.addAction(label)
        self._actions["loop"].setCheckable(True)
        self._more.setMenu(self._menu)

        self._sleep = QLineEdit("5.0")
        self._sleep.setFixedWidth(56)
        self._sleep_position = QLineEdit("-1")
        self._sleep_position.setFixedWidth(48)
        self._add_sleep = QPushButton("Add sleep")

        row.addWidget(QLabel("Iteration:"))
        row.addWidget(self._iterations)
        for button in (self._run_queue, self._pause, self._resume, self._stop, self._clear):
            row.addWidget(button)
        row.addWidget(self._more)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        row.addWidget(divider)
        row.addWidget(QLabel("Sleep(s):"))
        row.addWidget(self._sleep)
        row.addWidget(QLabel("Position:"))
        row.addWidget(self._sleep_position)
        row.addWidget(self._add_sleep)
        row.addStretch(1)
        return row

    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        return self._table

    def _build_details(self) -> QGroupBox:
        box = QGroupBox("Task Details")
        layout = QVBoxLayout(box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        inner = QVBoxLayout(content)
        self._task_title = QLabel()
        self._task_title.setProperty("role", "title")
        self._task_text = QLabel()
        self._task_text.setWordWrap(True)
        self._task_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._task_grid = ParamGrid()
        inner.addWidget(self._task_title)
        inner.addWidget(self._task_text)
        inner.addWidget(self._task_grid.widget)
        inner.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self._edit = QPushButton("Edit")
        self._save = QPushButton("Save")
        self._delete = QPushButton("Delete")
        for button in (self._edit, self._save, self._delete):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.set_task_editing(False, can_edit=False)
        return box

    # --- SchedulerView ------------------------------------------------------------

    def set_handlers(self, handlers: SchedulerHandlers) -> None:
        self._handlers = handlers
        self._run_queue.clicked.connect(lambda: handlers.on_run_queue(self._iterations.value()))
        self._pause.clicked.connect(handlers.on_pause)
        self._resume.clicked.connect(handlers.on_resume)
        self._stop.clicked.connect(handlers.on_stop)
        self._clear.clicked.connect(handlers.on_clear)
        self._add_sleep.clicked.connect(lambda: self._sleep_clicked(handlers))
        self._edit.clicked.connect(handlers.on_edit_task)
        self._save.clicked.connect(handlers.on_save_task)
        self._delete.clicked.connect(handlers.on_delete_task)
        self._actions["pause_now"].triggered.connect(handlers.on_pause_now)
        self._actions["stop_after_current"].triggered.connect(handlers.on_stop_after_current)
        self._actions["cancel_stop"].triggered.connect(handlers.on_cancel_stop)
        self._actions["abort"].triggered.connect(handlers.on_abort)
        self._actions["halt"].triggered.connect(handlers.on_halt)
        self._actions["loop"].triggered.connect(handlers.on_loop_changed)
        self._table.itemSelectionChanged.connect(
            lambda: handlers.on_row_selected(self._selected_uid())
        )
        self._table.customContextMenuRequested.connect(self._context_menu)

    def show_rows(self, rows: list[ScheduleRow]) -> None:
        selected = self._selected_uid()
        self._table.blockSignals(True)
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = (str(row.number), row.iteration,
                     f"{row.title}   {row.details}".rstrip(), row.status)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(_UID, row.uid)
                _style_cell(item, row.state)
                self._table.setItem(r, c, item)
            if row.uid and row.uid == selected:
                self._table.selectRow(r)
        self._table.blockSignals(False)

    def show_task_form(self, title: str, spec: PlanSpec, values: dict[str, FormValue]) -> None:
        self._task_title.setText(title)
        self._task_text.setText("")
        self._task_text.setVisible(False)
        self._task_grid.show(spec.params, values)
        self._task_grid.widget.setVisible(True)

    def show_task_text(self, title: str, text: str) -> None:
        self._task_title.setText(title)
        self._task_text.setText(text)
        self._task_text.setVisible(bool(text))
        self._task_grid.clear()
        self._task_grid.widget.setVisible(False)
        self.set_task_editing(False, can_edit=False)

    def set_task_editing(self, editing: bool, can_edit: bool) -> None:
        self._task_grid.set_read_only(not editing)
        self._edit.setEnabled(can_edit and not editing)
        self._save.setEnabled(editing)
        self._delete.setEnabled(can_edit)

    def read_task_values(self) -> dict[str, FormValue]:
        return self._task_grid.values()

    def show_task_errors(self, errors: dict[str, str]) -> None:
        self._task_grid.show_errors(errors)

    def enable_controls(self, controls: Controls, has_pending: bool, can_sleep: bool) -> None:
        self._run_queue.setEnabled(controls.start)
        self._pause.setEnabled(controls.pause)
        self._resume.setEnabled(controls.resume)
        self._stop.setEnabled(controls.stop)
        self._clear.setEnabled(controls.edit_queue and has_pending)
        self._add_sleep.setEnabled(can_sleep)
        self._actions["pause_now"].setEnabled(controls.pause)
        self._actions["stop_after_current"].setEnabled(controls.stop_after_current)
        self._actions["cancel_stop"].setEnabled(controls.cancel_stop)
        self._actions["abort"].setEnabled(controls.abort)
        self._actions["halt"].setEnabled(controls.halt)
        self._actions["loop"].setEnabled(controls.set_loop)

    def show_loop(self, loop: bool) -> None:
        self._actions["loop"].setChecked(loop)

    def reveal(self) -> None:
        self._reveal()

    # --- Helpers ------------------------------------------------------------------

    def row_count(self) -> int:
        return self._table.rowCount()

    def cell(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item else ""

    def select_row(self, row: int) -> None:
        self._table.selectRow(row)

    def _selected_uid(self) -> str | None:
        items = self._table.selectedItems()
        return items[0].data(_UID) if items else None

    def _sleep_clicked(self, handlers: SchedulerHandlers) -> None:
        try:
            seconds = float(self._sleep.text())
            position = int(self._sleep_position.text() or "-1")
        except ValueError:
            return
        handlers.on_add_sleep(seconds, position)

    def _context_menu(self, point: QPoint) -> None:
        item = self._table.itemAt(point)
        if item is None or self._handlers is None or not (uid := item.data(_UID)):
            return
        handlers = self._handlers
        menu = QMenu(self._table)
        menu.addAction("Move up", lambda: handlers.on_move(uid, -1))
        menu.addAction("Move down", lambda: handlers.on_move(uid, 1))
        menu.addAction("Duplicate", lambda: handlers.on_duplicate(uid))
        menu.addSeparator()
        menu.addAction("View plan source", lambda: handlers.on_view_source(uid))
        menu.exec(self._table.viewport().mapToGlobal(point))


def _style_cell(item: QTableWidgetItem, state: RowState) -> None:
    match state:
        case RowState.RUNNING:
            item.setBackground(QBrush(QColor(RUNNING_BG)))
            font = QFont()
            font.setBold(True)
            item.setFont(font)
        case RowState.FAILED:
            item.setForeground(QBrush(QColor(ERROR)))
        case RowState.DONE:
            item.setForeground(QBrush(QColor("#666666")))
        case RowState.PENDING:
            pass
