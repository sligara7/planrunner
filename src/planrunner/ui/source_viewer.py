"""Read-only plan source viewer: ScriptRunner's editor window, without editing.

Up to two plans side by side, with line numbers matching the file and Python
highlighting. Each pane names the local file it read.
"""

import keyword
import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from planrunner.sources import PlanSource
from planrunner.ui.style import ACCENT, HELP, MONO

MAX_PANES = 2


class SourceViewer:
    """``planrunner.controllers.source.SourceView``: a window of up to two panes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.window = QMainWindow(parent)
        self.window.setWindowTitle("Plan Source")
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self.window.setCentralWidget(self._splitter)
        self.window.resize(1300, 800)
        self._panes: list[_Pane] = []

    def show_source(self, title: str, source: PlanSource) -> None:
        for pane in self._panes:
            if pane.title == title:
                pane.load(source)
                break
        else:
            if len(self._panes) >= MAX_PANES:
                self._close(self._panes[-1])
            pane = _Pane(title, source, on_close=self._close)
            self._panes.append(pane)
            self._splitter.addWidget(pane.widget)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def titles(self) -> list[str]:
        return [pane.title for pane in self._panes]

    def _close(self, pane: "_Pane") -> None:
        if pane in self._panes:
            self._panes.remove(pane)
            pane.widget.setParent(None)
            pane.widget.deleteLater()
        if not self._panes:
            self.window.hide()


class _Pane:
    def __init__(self, title: str, source: PlanSource, on_close) -> None:
        self.title = title
        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        header = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet(f"color: {ACCENT}; font-weight: bold;")
        self._path = QLabel()
        self._path.setStyleSheet(f"color: {HELP};")
        close = QToolButton()
        close.setText("✕")
        close.clicked.connect(lambda: on_close(self))
        header.addWidget(name)
        header.addWidget(self._path, 1)
        header.addWidget(close)
        self.code = _CodeView()
        _PythonHighlighter(self.code.document())
        layout.addLayout(header)
        layout.addWidget(self.code, 1)
        self.load(source)

    def load(self, source: PlanSource) -> None:
        self._path.setText(f"{source.path}  (line {source.first_line})")
        self.code.show_code(source.text, source.first_line)


class _CodeView(QPlainTextEdit):
    """A read-only text view with a line-number gutter."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setFont(MONO)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._first_line = 1
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _: self._fit_gutter())
        self.updateRequest.connect(self._scroll_gutter)
        self._fit_gutter()

    def show_code(self, text: str, first_line: int) -> None:
        self._first_line = first_line
        self.setPlainText(text)
        self._fit_gutter()

    def gutter_width(self) -> int:
        digits = len(str(self._first_line + max(self.blockCount(), 1)))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor("#e0e0e0"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = round(self.blockBoundingRect(block).height())
        painter.setPen(QColor("#555555"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                painter.drawText(0, top, self._gutter.width() - 4, height,
                                 Qt.AlignmentFlag.AlignRight,
                                 str(block.blockNumber() + self._first_line))
            block = block.next()
            top += height

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(),
                                       rect.height()))

    def _fit_gutter(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())


class _Gutter(QWidget):
    def __init__(self, view: _CodeView) -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self._view.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._view.paint_gutter(event)


class _PythonHighlighter(QSyntaxHighlighter):

    def __init__(self, document) -> None:
        super().__init__(document)

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            f.setFontItalic(italic)
            return f

        self._rules = [
            (re.compile(r"\b(" + "|".join(keyword.kwlist) + r")\b"), fmt("#0000cc", bold=True)),
            (re.compile(r"\bdef\s+(\w+)"), fmt("#7a3e9d", bold=True)),
            (re.compile(r"@\w+(\.\w+)*"), fmt("#aa5500")),
            (re.compile(r"(\"\"\"|''').*?\1|\"[^\"\n]*\"|'[^'\n]*'"), fmt("#008000")),
            (re.compile(r"#[^\n]*"), fmt("#888888", italic=True)),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for pattern, style in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)
