"""Plan parameters: ScriptRunner's "Script parameters" panel.

The plan's name in blue and its description, one row per parameter, then
"Run now | Stop run ... Iteration | Position | Add to schedule", all in one
scrolling area as in ScriptRunner.
"""

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from planrunner.controllers.plans import PlansHandlers, ScheduleOptions
from planrunner.plan_params import FormValue, PlanSpec
from planrunner.ui.fields import ParamGrid


class PlanForm:
    def __init__(self, grid: ParamGrid | None = None) -> None:
        self.widget = QGroupBox("Plan parameters")
        outer = QVBoxLayout(self.widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        self._title = QLabel()
        self._title.setProperty("role", "title")
        self._description = QLabel()
        self._description.setProperty("role", "help")
        self._description.setWordWrap(True)
        self.grid = grid or ParamGrid()
        self._message = QLabel()
        self._message.setProperty("role", "help")

        self._run_now = QPushButton("Run now")
        self._stop_run = QPushButton("Stop run")
        self._iterations = QSpinBox()
        self._iterations.setRange(1, 999)
        self._position = QLineEdit("-1")
        self._position.setFixedWidth(48)
        self._add = QPushButton("Add to schedule")
        buttons = QHBoxLayout()
        buttons.addWidget(self._run_now)
        buttons.addWidget(self._stop_run)
        buttons.addStretch(1)
        buttons.addWidget(QLabel("Iteration:"))
        buttons.addWidget(self._iterations)
        buttons.addWidget(QLabel("Position:"))
        buttons.addWidget(self._position)
        buttons.addWidget(self._add)
        self._buttons = QWidget()
        self._buttons.setLayout(buttons)

        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addWidget(self._message)
        layout.addWidget(self.grid.widget)
        layout.addWidget(self._buttons)
        layout.addStretch(1)

    def set_handlers(self, handlers: PlansHandlers) -> None:
        self._run_now.clicked.connect(handlers.on_run_now)
        self._stop_run.clicked.connect(handlers.on_stop_run)
        self._add.clicked.connect(handlers.on_add_to_schedule)

    def show_plan(self, spec: PlanSpec, values: dict[str, FormValue]) -> None:
        self._title.setText(spec.name)
        self._description.setText(" ".join(spec.description.split()))
        self._description.setVisible(bool(spec.description))
        self._message.setText("" if spec.params else "This plan takes no parameters.")
        self._message.setVisible(not spec.params)
        self.grid.show(spec.params, values)
        self._buttons.setVisible(True)

    def clear(self, message: str) -> None:
        self._title.setText("")
        self._description.setVisible(False)
        self._message.setText(message)
        self._message.setVisible(True)
        self.grid.clear()
        self._buttons.setVisible(False)

    def current_plan(self) -> str:
        return self._title.text()

    def read_values(self) -> dict[str, FormValue]:
        return self.grid.values()

    def read_schedule_options(self) -> ScheduleOptions:
        try:
            position = int(self._position.text().strip() or "-1")
        except ValueError:
            position = -1
        return ScheduleOptions(iterations=self._iterations.value(), position=position)

    def show_errors(self, errors: dict[str, str]) -> None:
        self.grid.show_errors(errors)

    def enable_submit(self, schedule: bool, run_now: bool, stop: bool) -> None:
        self._add.setEnabled(schedule)
        self._run_now.setEnabled(run_now)
        self._stop_run.setEnabled(stop)
