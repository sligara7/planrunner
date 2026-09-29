"""Events the feeds and controllers exchange, and the bus that carries them.

Events are small frozen dataclasses. The bus hands each published event to the
injected ``Dispatcher``, so handlers always run on the UI thread, whichever
thread published.
"""

import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from planrunner.permissions import Permissions
from planrunner.protocols import JSON, Dispatcher, QueueServerAPI

# --- Connection ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Connected:
    uri: str
    api: QueueServerAPI


@dataclass(frozen=True, slots=True)
class Disconnected:
    uri: str


@dataclass(frozen=True, slots=True)
class PermissionsKnown:
    """What the connected user may do; published once per connection."""

    allowed: Permissions


@dataclass(frozen=True, slots=True)
class ServerReachable:
    """The status feed reached the server (first time, or again after a failure)."""


@dataclass(frozen=True, slots=True)
class ServerUnreachable:
    """The status feed could not reach the server; ``error`` says why."""

    error: str


# --- Server state -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusUpdated:
    status: JSON


@dataclass(frozen=True, slots=True)
class QueueUpdated:
    running_item: JSON | None
    items: tuple[JSON, ...]


@dataclass(frozen=True, slots=True)
class HistoryUpdated:
    items: tuple[JSON, ...]


@dataclass(frozen=True, slots=True)
class AllowedChanged:
    """The server's allowed plans or devices changed and should be fetched again."""


@dataclass(frozen=True, slots=True)
class ConsoleText:
    text: str


# --- UI requests --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Notice:
    """A line for the console and status bar."""

    text: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class EditItemRequested:
    """Load a queued item into the plan form for editing."""

    item: JSON


# --- Bus ----------------------------------------------------------------------


@dataclass(slots=True)
class EventBus:
    """Type-keyed publish/subscribe. ``publish`` is safe from any thread."""

    dispatcher: Dispatcher
    _handlers: defaultdict[type, list[Callable[[Any], None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe[E](self, event_type: type[E], handler: Callable[[E], None]) -> Callable[[], None]:
        with self._lock:
            self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers[event_type]:
                    self._handlers[event_type].remove(handler)

        return unsubscribe

    def publish(self, event: object) -> None:
        self.dispatcher.post(lambda: self._deliver(event))

    def _deliver(self, event: object) -> None:
        with self._lock:
            handlers = list(self._handlers.get(type(event), ()))
        for handler in handlers:
            handler(event)
