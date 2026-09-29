"""The status strip: RE Manager state at a glance."""

from typing import Protocol

from planrunner.events import (
    Disconnected,
    ServerReachable,
    ServerUnreachable,
    StatusUpdated,
)
from planrunner.protocols import JSON, EventSubscriber
from planrunner.status_text import StatusField, status_fields


class StatusView(Protocol):
    def show_fields(self, fields: list[StatusField]) -> None: ...


class StatusController:
    def __init__(self, *, view: StatusView, bus: EventSubscriber) -> None:
        self._view = view
        self._status: JSON | None = None
        self._reachable = True

        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(ServerUnreachable, lambda _: self._set_reachable(False))
        bus.subscribe(ServerReachable, lambda _: self._set_reachable(True))
        bus.subscribe(Disconnected, lambda _: self._on_disconnected())
        self._render()

    def _on_status(self, event: StatusUpdated) -> None:
        self._status = event.status
        self._render()

    def _set_reachable(self, reachable: bool) -> None:
        self._reachable = reachable
        self._render()

    def _on_disconnected(self) -> None:
        self._status, self._reachable = None, True
        self._render()

    def _render(self) -> None:
        self._view.show_fields(status_fields(self._status, self._reachable))
