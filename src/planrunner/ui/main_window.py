"""The main window, laid out as ScriptRunner is (see scriptrunner/figs/fig1-2):

    Queue server bar            (ScriptRunner: Base folder path)
    Environment bar             (ScriptRunner: Python environment path)
    Available plans | Plan parameters
    ── ▼ Show scheduler ──
    Scheduler                   (hidden until something is added)
    Console output | Save to log file
    status bar
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from planrunner.ui.console_panel import ConsolePanel
from planrunner.ui.plan_form import PlanForm
from planrunner.ui.plan_list import PlanList
from planrunner.ui.scheduler import SchedulerPanel
from planrunner.ui.services import StatusBar
from planrunner.ui.source_viewer import SourceViewer
from planrunner.ui.top_bars import EnvironmentBar, ServerBar, TopBars

SCREEN_FRACTION = 0.85


class MainWindow:
    def __init__(self, title: str = "Plan Runner") -> None:
        self.window = _Window()
        self.window.setWindowTitle(title)

        self.server_bar = ServerBar()
        self.environment_bar = EnvironmentBar()
        self.top_bars = TopBars(self.server_bar, self.environment_bar)
        self.plan_list = PlanList()
        self.plan_form = PlanForm()
        self.scheduler = SchedulerPanel(reveal=lambda: self.set_scheduler_visible(True))
        self.console = ConsolePanel()
        self.status_bar = StatusBar(self.window.statusBar())
        self.source_viewer = SourceViewer(self.window)

        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.addWidget(self.plan_list.widget)
        middle.addWidget(self.plan_form.widget)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 3)

        self.scheduler_visible = False
        self._toggle = QPushButton()
        self._toggle.clicked.connect(lambda: self.set_scheduler_visible(not self.scheduler_visible))
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(_line(), 1)
        toggle_row.addWidget(self._toggle)
        toggle_row.addWidget(_line(), 1)
        scheduler_block = QWidget()
        block = QVBoxLayout(scheduler_block)
        block.setContentsMargins(0, 0, 0, 0)
        block.addLayout(toggle_row)
        block.addWidget(self.scheduler.widget, 1)

        body = QSplitter(Qt.Orientation.Vertical)
        body.addWidget(middle)
        body.addWidget(scheduler_block)
        body.addWidget(self.console.widget)
        body.setStretchFactor(0, 5)
        body.setStretchFactor(1, 4)
        body.setStretchFactor(2, 2)
        body.setChildrenCollapsible(False)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 0)
        layout.addWidget(self.server_bar.widget)
        layout.addWidget(self.environment_bar.widget)
        layout.addWidget(body, 1)
        self.window.setCentralWidget(central)

        self.set_scheduler_visible(False)  # as ScriptRunner starts: scheduler hidden
        self._fit_to_screen()

    def set_scheduler_visible(self, visible: bool) -> None:
        self.scheduler_visible = visible
        self.scheduler.widget.setVisible(visible)
        self._toggle.setText("▲ Hide scheduler" if visible else "▼ Show scheduler")

    def on_close(self, callback) -> None:
        self.window.close_callback = callback

    def show(self) -> None:
        self.window.show()

    def _fit_to_screen(self) -> None:
        screen = self.window.screen().availableGeometry()
        width = int(screen.width() * SCREEN_FRACTION)
        height = int(screen.height() * SCREEN_FRACTION)
        self.window.resize(width, height)
        self.window.move(screen.x() + (screen.width() - width) // 2,
                         screen.y() + (screen.height() - height) // 2)


class _Window(QMainWindow):
    """A QMainWindow that reports its close to a callback (Qt delivers close as an event)."""

    close_callback = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self.close_callback is not None:
            self.close_callback()
        event.accept()


def _line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
