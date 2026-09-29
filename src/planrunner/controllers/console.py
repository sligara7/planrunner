"""The console: RE worker output and GUI notices, optionally saved to a log file."""

import logging
import time
from pathlib import Path
from typing import Protocol

from planrunner.events import ConsoleText, Notice, ServerUnreachable
from planrunner.protocols import ConfigStore, Dialogs, EventSubscriber, StatusLine

logger = logging.getLogger(__name__)


class ConsoleHandlers(Protocol):
    def on_log_toggled(self, enabled: bool) -> None: ...

    def on_choose_log_file(self) -> None: ...

    def on_clear(self) -> None: ...


class ConsoleView(Protocol):
    def set_handlers(self, handlers: ConsoleHandlers) -> None: ...

    def append(self, text: str, tag: str) -> None:
        """``tag`` is 'output' (worker console), 'info' or 'error' (GUI notices)."""
        ...

    def clear(self) -> None: ...

    def show_log_file(self, path: str | None, enabled: bool) -> None: ...


class LogFile:
    """Appends timestamped lines to a text file; a write failure turns it off."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.enabled = False

    def write(self, text: str) -> str | None:
        """Write ``text``; return an error message if the write failed."""
        if not (self.enabled and self.path):
            return None
        stamp = time.strftime("[%Y-%m-%d %H:%M:%S] ")
        lines = "".join(stamp + line for line in text.splitlines(keepends=True))
        try:
            with self.path.open("a") as f:
                f.write(lines if lines.endswith("\n") else lines + "\n")
        except OSError as ex:
            self.enabled = False
            return f"Log file disabled: {ex}"
        return None


class ConsoleController:
    def __init__(
        self,
        *,
        view: ConsoleView,
        status_line: StatusLine,
        bus: EventSubscriber,
        dialogs: Dialogs,
        config: ConfigStore,
        log: LogFile | None = None,
    ) -> None:
        self._view = view
        self._status_line = status_line
        self._dialogs = dialogs
        self._config = config
        self._log = log or LogFile()
        if saved := config.load().get("log_file"):
            self._log.path = Path(saved)

        view.set_handlers(self)
        view.show_log_file(self._path_text(), enabled=False)
        bus.subscribe(ConsoleText, lambda e: self._append(e.text, "output"))
        bus.subscribe(Notice, self._on_notice)
        bus.subscribe(ServerUnreachable, lambda e: self._on_notice(
            Notice(f"Server unreachable: {e.error}", is_error=True)))

    def on_log_toggled(self, enabled: bool) -> None:
        if enabled and self._log.path is None:
            self.on_choose_log_file()
            enabled = self._log.path is not None
        self._log.enabled = enabled
        self._view.show_log_file(self._path_text(), enabled)
        if enabled:
            self._append(f">>> Saving console output to {self._log.path}\n", "info")

    def on_choose_log_file(self) -> None:
        initial = self._log.path.name if self._log.path else "planrunner_log.txt"
        if path := self._dialogs.ask_save_path("Save console output to", initial):
            self._log.path = Path(path)
            self._log.enabled = True
            self._config.save({"log_file": path})
            self._view.show_log_file(self._path_text(), enabled=True)

    def on_clear(self) -> None:
        self._view.clear()

    def _on_notice(self, notice: Notice) -> None:
        self._status_line.set_message(notice.text)
        self._append(f">>> {notice.text}\n", "error" if notice.is_error else "info")

    def _append(self, text: str, tag: str) -> None:
        self._view.append(text, tag)
        if error := self._log.write(text):
            self._view.show_log_file(self._path_text(), enabled=False)
            self._view.append(f"!!! {error}\n", "error")

    def _path_text(self) -> str | None:
        return str(self._log.path) if self._log.path else None
