"""The two slim bars across the top, in the places of ScriptRunner's two.

"Queue server" (ScriptRunner: "Base folder path"): address, state, Connect, Disconnect,
and an API key dialog (usually unnecessary: the key is found automatically).
"Environment" (ScriptRunner: "Python environment path"): the RE Manager's state and
Open / Close for the RE worker environment.
"""

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
)

from planrunner.controllers.connection import ConnectionForm, ConnectionHandlers
from planrunner.status_text import StatusField, Tone
from planrunner.ui.style import tone_color

_STATES = {
    "disconnected": ("○ Not connected", Tone.WARN),
    "connecting": ("… Connecting", Tone.BUSY),
    "connected": ("● Connected", Tone.GOOD),
    "unreachable": ("⚠ Unreachable", Tone.BAD),
}


def _bar() -> tuple[QFrame, QHBoxLayout]:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(8, 4, 8, 4)
    return frame, layout


class ServerBar:
    def __init__(self) -> None:
        self.widget, layout = _bar()
        self._uri = QLineEdit()
        self._uri.setPlaceholderText("http://localhost:60610")
        self._state = QLabel()
        self._access = QLabel()
        self._connect = QPushButton("Connect")
        self._disconnect = QPushButton("Disconnect")
        self._key_button = QPushButton("API key…")
        self._api_key = ""
        layout.addWidget(QLabel("Queue server:"))
        layout.addWidget(self._uri, 1)
        layout.addWidget(self._state)
        layout.addWidget(self._access)
        layout.addWidget(self._key_button)
        layout.addWidget(self._connect)
        layout.addWidget(self._disconnect)
        self._key_button.clicked.connect(self._ask_key)

    def set_handlers(self, handlers: ConnectionHandlers) -> None:
        self._connect.clicked.connect(handlers.on_connect)
        self._disconnect.clicked.connect(handlers.on_disconnect)
        self._uri.returnPressed.connect(handlers.on_connect)

    def read_form(self) -> ConnectionForm:
        return ConnectionForm(uri=self._uri.text(), api_key=self._api_key)

    def fill_form(self, form: ConnectionForm) -> None:
        self._uri.setText(form.uri)
        self._set_key(form.api_key)

    def show_connection(self, state: str) -> None:
        text, tone = _STATES[state]
        self._state.setText(text)
        self._state.setStyleSheet(f"color: {tone_color(tone)}; font-weight: bold;")
        self._connect.setEnabled(state != "connecting")
        self._disconnect.setEnabled(state in ("connected", "unreachable"))

    def show_access(self, text: str) -> None:
        tone = Tone.WARN if text == "read only" else Tone.NORMAL
        self._access.setText(f"({text})" if text else "")
        self._access.setStyleSheet(f"color: {tone_color(tone)};")

    def _ask_key(self) -> None:
        key, ok = QInputDialog.getText(
            self.widget, "API key",
            "API key for this server (leave empty to use the one the beamline deploys):",
            QLineEdit.EchoMode.Password, self._api_key,
        )
        if ok:
            self._set_key(key.strip())

    def _set_key(self, key: str) -> None:
        self._api_key = key
        self._key_button.setText("API key ✓" if key else "API key…")


class EnvironmentBar:
    def __init__(self) -> None:
        self.widget, layout = _bar()
        self._fields = QLabel()
        self._open = QPushButton("Open")
        self._close = QPushButton("Close")
        layout.addWidget(QLabel("Environment:"))
        layout.addWidget(self._fields, 1)
        layout.addWidget(self._open)
        layout.addWidget(self._close)

    def set_handlers(self, handlers: ConnectionHandlers) -> None:
        self._open.clicked.connect(handlers.on_open_environment)
        self._close.clicked.connect(handlers.on_close_environment)

    def enable_environment_buttons(self, can_open: bool, can_close: bool) -> None:
        self._open.setEnabled(can_open)
        self._close.setEnabled(can_close)

    def show_fields(self, fields: list[StatusField]) -> None:
        parts = [
            f"{f.label}: <b style='color:{tone_color(f.tone)}'>{f.value}</b>" for f in fields
        ]
        self._fields.setText(" &nbsp;·&nbsp; ".join(parts))


class TopBars:
    """Both bars together, as the ``ConnectionView`` the connection controller drives."""

    def __init__(self, server: ServerBar, environment: EnvironmentBar) -> None:
        self.server = server
        self.environment = environment

    def set_handlers(self, handlers: ConnectionHandlers) -> None:
        self.server.set_handlers(handlers)
        self.environment.set_handlers(handlers)

    def read_form(self) -> ConnectionForm:
        return self.server.read_form()

    def fill_form(self, form: ConnectionForm) -> None:
        self.server.fill_form(form)

    def show_connection(self, state: str) -> None:
        self.server.show_connection(state)

    def show_access(self, text: str) -> None:
        self.server.show_access(text)

    def enable_environment_buttons(self, can_open: bool, can_close: bool) -> None:
        self.environment.enable_environment_buttons(can_open, can_close)
