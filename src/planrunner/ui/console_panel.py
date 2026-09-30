"""The console: ScriptRunner's "Console output | Save to log file" panel."""

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from planrunner.controllers.console import ConsoleHandlers
from planrunner.ui.style import ACCENT, CONSOLE_BG, ERROR, MONO, MUTED

MAX_LINES = 5000
_COLORS = {"output": "#111111", "info": ACCENT, "error": ERROR}


class ConsolePanel:
    def __init__(self) -> None:
        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._log_enabled = QCheckBox("Console output | Save to log file:")
        self._log_path = QLabel()
        self._choose = QPushButton("Select File")
        self._clear = QPushButton("Clear")
        row.addWidget(self._log_enabled)
        row.addWidget(self._log_path, 1)
        row.addWidget(self._choose)
        row.addWidget(self._clear)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(MONO)
        self._text.setMaximumBlockCount(MAX_LINES)
        self._text.setStyleSheet(f"background: {CONSOLE_BG};")
        layout.addLayout(row)
        layout.addWidget(self._text, 1)

    def set_handlers(self, handlers: ConsoleHandlers) -> None:
        self._log_enabled.clicked.connect(handlers.on_log_toggled)
        self._choose.clicked.connect(handlers.on_choose_log_file)
        self._clear.clicked.connect(handlers.on_clear)

    def append(self, text: str, tag: str) -> None:
        bar = self._text.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        cursor = QTextCursor(self._text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_COLORS.get(tag, "#111111")))
        cursor.insertText(text, fmt)
        if at_bottom:
            bar.setValue(bar.maximum())

    def clear(self) -> None:
        self._text.clear()

    def text(self) -> str:
        return self._text.toPlainText()

    def show_log_file(self, path: str | None, enabled: bool) -> None:
        self._log_enabled.setChecked(enabled)
        self._log_path.setText(path or "")
        color = ACCENT if enabled else MUTED
        self._log_path.setStyleSheet(f"color: {color}; font-style: italic;")
