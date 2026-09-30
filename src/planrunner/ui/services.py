"""Qt implementations of the small UI services controllers depend on."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox, QStatusBar, QWidget

from planrunner.dispatch import QueueDispatcher


class QtDialogs:
    """``planrunner.protocols.Dialogs`` using Qt's standard dialogs."""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent

    def confirm(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(self._parent, title, message)
        return answer == QMessageBox.StandardButton.Yes

    def error(self, title: str, message: str) -> None:
        QMessageBox.critical(self._parent, title, message)

    def ask_save_path(self, title: str, initial_file: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self._parent, title, str(Path.home() / initial_file),
            "Text files (*.txt);;All files (*)",
        )
        return path or None


class StatusBar:
    """``planrunner.protocols.StatusLine``: the status bar along the bottom."""

    def __init__(self, bar: QStatusBar) -> None:
        self._bar = bar

    def set_message(self, text: str) -> None:
        self._bar.showMessage(text)


class QtPump:
    """Drains a ``QueueDispatcher`` on the Qt event loop every ``interval_ms``."""

    def __init__(self, dispatcher: QueueDispatcher, interval_ms: int = 50) -> None:
        self._dispatcher = dispatcher
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(dispatcher.drain)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
