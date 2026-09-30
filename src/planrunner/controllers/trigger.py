"""The operator's event trigger for a camera the running plan is waiting on.

Offers a Trigger control while a plan runs with a camera that takes an event
trigger (see ``planrunner.triggers``), and sends it by asking the queueserver to
run the profile's ``send_event_trigger`` in the background: planrunner never
writes the trigger PV itself.
"""

from collections.abc import Callable
from typing import Protocol

from planrunner.controllers.catalog import CatalogStore
from planrunner.controllers.commands import Commands
from planrunner.events import (
    CatalogCleared,
    CatalogUpdated,
    Disconnected,
    Notice,
    PermissionsKnown,
    QueueUpdated,
    StatusUpdated,
)
from planrunner.permissions import Permissions
from planrunner.protocols import JSON, EventBusLike, QueueServerAPI
from planrunner.triggers import TRIGGER_FUNCTION, trigger_targets

TASK_TIMEOUT = 30.0
"""Seconds to wait for the worker to report the trigger function's result."""


class TriggerView(Protocol):
    def set_trigger_handler(self, handler: Callable[[str], None]) -> None:
        """``handler(camera)`` is called when the operator triggers ``camera``."""
        ...

    def show_trigger_targets(self, cameras: tuple[str, ...]) -> None:
        """The cameras that can be triggered now; empty disables the control."""
        ...


class TriggerController:
    def __init__(self, *, view: TriggerView, catalog: CatalogStore, commands: Commands,
                 bus: EventBusLike) -> None:
        self._view = view
        self._catalog = catalog
        self._commands = commands
        self._bus = bus
        self._running_item: JSON | None = None
        self._running = False
        self._allowed = Permissions.full()

        view.set_trigger_handler(self.trigger)
        bus.subscribe(QueueUpdated, self._on_queue)
        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(PermissionsKnown, self._on_permissions)
        bus.subscribe(CatalogUpdated, lambda _: self._refresh())
        bus.subscribe(CatalogCleared, lambda _: self._refresh())
        bus.subscribe(Disconnected, lambda _: self._forget())

    @property
    def targets(self) -> tuple[str, ...]:
        if not (self._running and self._allowed.execute):
            return ()
        return trigger_targets(self._running_item, self._catalog.catalog)

    def trigger(self, camera: str) -> None:
        def call(api: QueueServerAPI) -> str:
            item = {"item_type": "function", "name": TRIGGER_FUNCTION, "args": [camera]}
            task_uid = api.function_execute(item, run_in_background=True)["task_uid"]
            api.wait_for_completed_task(task_uid, timeout=TASK_TIMEOUT)
            result = api.task_result(task_uid)["result"]
            if not result.get("success"):
                raise RuntimeError(result.get("msg") or "the trigger function failed")
            return str(result.get("return_value") or f"Event trigger sent to {camera}")

        self._commands.send(f"Trigger {camera}", call,
                            lambda message: self._bus.publish(Notice(message)),
                            announce=False)

    def _on_queue(self, event: QueueUpdated) -> None:
        self._running_item = event.running_item
        self._refresh()

    def _on_status(self, event: StatusUpdated) -> None:
        running = event.status.get("manager_state") in ("executing_queue", "executing_task")
        if running != self._running:
            self._running = running
            self._refresh()

    def _on_permissions(self, event: PermissionsKnown) -> None:
        self._allowed = event.allowed
        self._refresh()

    def _forget(self) -> None:
        self._running_item, self._running = None, False
        self._refresh()

    def _refresh(self) -> None:
        self._view.show_trigger_targets(self.targets)
