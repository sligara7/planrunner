"""Typing seams between planrunner's layers.

Every collaborator that crosses a layer boundary is described here as a
``typing.Protocol``, so the concrete implementation can be swapped (or faked in
tests) without touching the code that uses it. View protocols live next to the
controller that needs them, in ``planrunner.controllers``.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

type JSON = dict[str, Any]


# ------------------------------------------------------------------------------
#                       The queueserver, as planrunner uses it
# ------------------------------------------------------------------------------


class ConsoleMonitor(Protocol):
    """``REManagerAPI.console_monitor``: a buffered stream of console messages."""

    def enable(self) -> None: ...

    def disable(self) -> None: ...

    def next_msg(self, timeout: float | None = None) -> JSON:
        """Return ``{"time": float, "msg": str}``; raise if nothing arrives in time."""
        ...


class QueueServerAPI(Protocol):
    """The subset of ``bluesky_queueserver_api.http.REManagerAPI`` planrunner calls.

    Every method returns the server's response dict. The real client raises
    when the server answers ``success: False``.
    """

    @property
    def console_monitor(self) -> ConsoleMonitor: ...

    def status(self, *, reload: bool = False) -> JSON: ...

    def api_scopes(self) -> JSON:
        """``{"roles": [...], "scopes": [...]}`` for the current credentials."""
        ...

    def plans_allowed(self, *, reload: bool = False) -> JSON: ...

    def devices_allowed(self, *, reload: bool = False) -> JSON: ...

    def queue_get(self, *, reload: bool = False) -> JSON: ...

    def history_get(self, *, reload: bool = False) -> JSON: ...

    def item_add_batch(self, items: Sequence[JSON], *, pos: int | str | None = None) -> JSON: ...

    def item_update(self, item: JSON, *, replace: bool | None = None) -> JSON: ...

    def item_move(self, *, uid: str | None = None, pos_dest: int | str | None = None) -> JSON: ...

    def item_remove(self, *, uid: str | None = None) -> JSON: ...

    def item_execute(self, item: JSON) -> JSON: ...

    def queue_start(self) -> JSON: ...

    def queue_stop(self) -> JSON: ...

    def queue_stop_cancel(self) -> JSON: ...

    def queue_clear(self) -> JSON: ...

    def queue_mode_set(self, **kwargs: Any) -> JSON: ...

    def re_pause(self, option: str | None = None) -> JSON: ...

    def re_resume(self) -> JSON: ...

    def re_stop(self) -> JSON: ...

    def re_abort(self) -> JSON: ...

    def re_halt(self) -> JSON: ...

    def environment_open(self) -> JSON: ...

    def environment_close(self) -> JSON: ...

    def function_execute(self, item: JSON, *, run_in_background: bool = False) -> JSON:
        """Run an allowed function in the worker; returns ``task_uid`` to follow it."""
        ...

    def wait_for_completed_task(self, task_uid: str, *, timeout: float = 60) -> Any: ...

    def task_result(self, task_uid: str) -> JSON:
        """``{"result": {"success", "msg", "return_value", ...}}`` once completed."""
        ...

    def close(self) -> None: ...


# ------------------------------------------------------------------------------
#                       Threading and events
# ------------------------------------------------------------------------------


class Dispatcher(Protocol):
    """Runs callbacks on the UI thread. ``post`` must be safe from any thread."""

    def post(self, callback: Callable[[], None]) -> None: ...


class EventPublisher(Protocol):
    """Publishes an event to its subscribers; safe to call from any thread."""

    def publish(self, event: object) -> None: ...


class EventSubscriber(Protocol):
    def subscribe[E](self, event_type: type[E], handler: Callable[[E], None]) -> Callable[[], None]:
        """Call ``handler`` for every ``event_type`` event; returns an unsubscribe function."""
        ...


class EventBusLike(EventPublisher, EventSubscriber, Protocol):
    """Both halves of the bus, for collaborators that publish and subscribe."""


@dataclass(frozen=True, slots=True)
class Outcome[T]:
    """The result of a server call: ``value`` on success, ``error`` on failure."""

    value: T | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


type ApiCall[T] = Callable[[QueueServerAPI], T]
type DoneCallback[T] = Callable[[Outcome[T]], None]


class CallRunner(Protocol):
    """Runs a server call off the UI thread and reports its outcome on the UI thread."""

    def run[T](self, call: ApiCall[T], on_done: DoneCallback[T] | None = None) -> None: ...


class Feed(Protocol):
    """A background source of events from the server (status, console, ...)."""

    def start(self, api: QueueServerAPI) -> None: ...

    def stop(self) -> None: ...


# ------------------------------------------------------------------------------
#                       UI services
# ------------------------------------------------------------------------------


class Dialogs(Protocol):
    """Modal questions and notices, so controllers never import tkinter."""

    def confirm(self, title: str, message: str) -> bool: ...

    def error(self, title: str, message: str) -> None: ...

    def ask_save_path(self, title: str, initial_file: str) -> str | None: ...


class StatusLine(Protocol):
    """The one-line status bar at the bottom of the window."""

    def set_message(self, text: str) -> None: ...


class ConfigStore(Protocol):
    """Where user preferences (last server, window state, ...) persist."""

    def load(self) -> Mapping[str, Any]: ...

    def save(self, data: Mapping[str, Any]) -> None: ...
