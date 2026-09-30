"""Look and feel: ScriptRunner's calm light-grey window with blue accents, in Qt.

Colours follow ScriptRunner (``scriptrunner/lib/utilities.py``). The palette is set
explicitly, so a dark desktop theme cannot turn the window unreadable.
"""

from importlib.resources import files

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from planrunner.status_text import Tone

ACCENT = "#0055aa"
HELP = "#555555"
ERROR = "#c00000"
MUTED = "#888888"
WINDOW_BG = "#ececec"
CONSOLE_BG = "#f4f4f4"
SELECT_BG = "#cce8ff"
RUNNING_BG = "#dff5e1"
MONO = QFont("Monospace")
MONO.setStyleHint(QFont.StyleHint.TypeWriter)
MONO.setPointSize(10)

TONE_COLORS = {
    Tone.NORMAL: "#222222",
    Tone.GOOD: "#1a7f37",
    Tone.BUSY: "#0055aa",
    Tone.WARN: "#b35900",
    Tone.BAD: "#c00000",
}

STYLESHEET = f"""
QGroupBox {{ font-weight: normal; margin-top: 1.1em; border: 1px solid #c8c8c8;
             border-radius: 3px; padding-top: 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #333; }}
QPushButton {{ padding: 4px 14px; }}
QTableWidget, QTreeWidget, QListWidget {{ selection-background-color: {SELECT_BG};
                                          selection-color: black; }}
QLabel[role="title"] {{ color: {ACCENT}; font-size: 13pt; }}
QLabel[role="type"] {{ color: {ACCENT}; }}
QLabel[role="help"] {{ color: {HELP}; }}
QLabel[role="error"] {{ color: {ERROR}; }}
QLabel[role="path"] {{ color: {ACCENT}; font-style: italic; }}
"""


def apply_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(WINDOW_BG))
    palette.setColor(QPalette.ColorRole.Base, QColor("white"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#111111"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#111111"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#e4e4e4"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#111111"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(SELECT_BG))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("black"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(MUTED))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())


def app_icon() -> QIcon:
    """ScriptRunner's icon (Apache-2.0, Nghia Vo), which HEX users already know."""
    return QIcon(str(files("planrunner.assets") / "planrunner.png"))


def tone_color(tone: Tone) -> str:
    return TONE_COLORS[tone]
