"""The scheduler: the server's plan queue, its history, and queue/RunEngine control."""

from dataclasses import dataclass
from typing import Protocol

from planrunner.controllers.commands import Commands
from planrunner.events import (
    Disconnected,
    EditItemRequested,
    HistoryUpdated,
    PermissionsKnown,
    QueueUpdated,
    StatusUpdated,
)
from planrunner.permissions import Permissions
from planrunner.protocols import JSON, Dialogs, EventPublisher, EventSubscriber
from planrunner.status_text import (
    Controls,
    controls_for,
    item_details,
    item_title,
    parameters_text,
    result_text,
    time_text,
)


@dataclass(frozen=True, slots=True)
class QueueRow:
    uid: str
    position: str
    title: str
    parameters: str
    user: str
    running: bool = False


@dataclass(frozen=True, slots=True)
class HistoryRow:
    index: int
    title: str
    parameters: str
    result: str
    finished: str
    failed: bool


class QueueHandlers(Protocol):
    def on_start(self) -> None: ...

    def on_stop_after_current(self) -> None: ...

    def on_cancel_stop(self) -> None: ...

    def on_pause(self, immediate: bool) -> None: ...

    def on_resume(self) -> None: ...

    def on_stop_run(self) -> None: ...

    def on_abort(self) -> None: ...

    def on_halt(self) -> None: ...

    def on_clear(self) -> None: ...

    def on_loop_changed(self, loop: bool) -> None: ...

    def on_item_selected(self, uid: str | None) -> None: ...

    def on_move(self, uid: str, offset: int) -> None: ...

    def on_edit(self, uid: str) -> None: ...

    def on_duplicate(self, uid: str) -> None: ...

    def on_delete(self, uid: str) -> None: ...

    def on_history_selected(self, index: int | None) -> None: ...

    def on_requeue(self, index: int) -> None: ...


class QueueView(Protocol):
    def set_handlers(self, handlers: QueueHandlers) -> None: ...

    def show_queue(self, rows: list[QueueRow]) -> None: ...

    def show_history(self, rows: list[HistoryRow]) -> None: ...

    def show_item_details(self, text: str) -> None: ...

    def show_history_details(self, text: str) -> None: ...

    def enable_controls(self, controls: Controls, has_queue: bool) -> None: ...

    def show_loop(self, loop: bool) -> None: ...


class QueueController:
    def __init__(
        self,
        *,
        view: QueueView,
        commands: Commands,
        bus: EventSubscriber,
        publisher: EventPublisher,
        dialogs: Dialogs,
    ) -> None:
        self._view = view
        self._commands = commands
        self._publish = publisher.publish
        self._dialogs = dialogs
        self._running: JSON | None = None
        self._items: list[JSON] = []
        self._history: list[JSON] = []
        self._status: JSON | None = None
        self._allowed = Permissions.full()

        view.set_handlers(self)
        view.enable_controls(Controls(), has_queue=False)
        bus.subscribe(QueueUpdated, self._on_queue)
        bus.subscribe(HistoryUpdated, self._on_history)
        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(PermissionsKnown, self._on_permissions)
        bus.subscribe(Disconnected, lambda _: self._on_disconnected())

    # --- Queue control ----------------------------------------------------------

    def on_start(self) -> None:
        self._commands.send("Start queue", lambda api: api.queue_start())

    def on_stop_after_current(self) -> None:
        self._commands.send("Stop after current plan", lambda api: api.queue_stop())

    def on_cancel_stop(self) -> None:
        self._commands.send("Cancel stop", lambda api: api.queue_stop_cancel())

    def on_clear(self) -> None:
        if self._items and self._dialogs.confirm(
            "Clear queue", f"Remove all {len(self._items)} queued items?"
        ):
            self._commands.send("Clear queue", lambda api: api.queue_clear())

    def on_loop_changed(self, loop: bool) -> None:
        self._commands.send(
            f"Loop mode {'on' if loop else 'off'}", lambda api: api.queue_mode_set(loop=loop)
        )

    # --- RunEngine control ------------------------------------------------------

    def on_pause(self, immediate: bool) -> None:
        option = "immediate" if immediate else "deferred"
        what = "Pause now" if immediate else "Pause at next checkpoint"
        self._commands.send(what, lambda api: api.re_pause(option))

    def on_resume(self) -> None:
        self._commands.send("Resume", lambda api: api.re_resume())

    def on_stop_run(self) -> None:
        self._commands.send("Stop run (success)", lambda api: api.re_stop())

    def on_abort(self) -> None:
        if self._dialogs.confirm("Abort", "Abort the paused plan? The run is marked as aborted."):
            self._commands.send("Abort", lambda api: api.re_abort())

    def on_halt(self) -> None:
        if self._dialogs.confirm(
            "Halt", "Halt the paused plan immediately, without cleanup? Use only in emergencies."
        ):
            self._commands.send("Halt", lambda api: api.re_halt())

    # --- Queue items ------------------------------------------------------------

    def on_item_selected(self, uid: str | None) -> None:
        item = self._find(uid)
        self._view.show_item_details(item_details(item) if item else "")

    def on_move(self, uid: str, offset: int) -> None:
        index = next((i for i, it in enumerate(self._items) if it.get("item_uid") == uid), None)
        if index is None:
            return
        destination = index + offset
        if 0 <= destination < len(self._items):
            self._commands.send(
                "Move item",
                lambda api: api.item_move(uid=uid, pos_dest=destination),
                announce=False,
            )

    def on_edit(self, uid: str) -> None:
        if (item := self._find(uid)) is not None:
            self._publish(EditItemRequested(item))

    def on_duplicate(self, uid: str) -> None:
        if (item := self._find(uid)) is not None:
            copy = {k: v for k, v in item.items() if k not in ("item_uid", "result")}
            index = self._items.index(item)
            self._commands.send(
                f"Duplicate {item_title(item)}",
                lambda api: api.item_add_batch([copy], pos=index + 1),
            )

    def on_delete(self, uid: str) -> None:
        if (item := self._find(uid)) is not None and self._dialogs.confirm(
            "Delete", f"Remove '{item_title(item)}' from the queue?"
        ):
            self._commands.send(f"Delete {item_title(item)}", lambda api: api.item_remove(uid=uid))

    # --- History ----------------------------------------------------------------

    def on_history_selected(self, index: int | None) -> None:
        if index is None or not 0 <= index < len(self._history):
            self._view.show_history_details("")
        else:
            self._view.show_history_details(item_details(self._history[index]))

    def on_requeue(self, index: int) -> None:
        if 0 <= index < len(self._history):
            old = self._history[index]
            item = {k: v for k, v in old.items() if k not in ("item_uid", "result")}
            self._commands.send(
                f"Queue {item_title(item)} again", lambda api: api.item_add_batch([item])
            )

    # --- Events -----------------------------------------------------------------

    def _on_queue(self, event: QueueUpdated) -> None:
        self._running = event.running_item
        self._items = list(event.items)
        rows = []
        if self._running:
            rows.append(self._row(self._running, "▶", running=True))
        rows += [self._row(item, str(i)) for i, item in enumerate(self._items, start=1)]
        self._view.show_queue(rows)

    def _on_history(self, event: HistoryUpdated) -> None:
        self._history = list(event.items)
        rows = [
            HistoryRow(
                index=i,
                title=item_title(item),
                parameters=parameters_text(item),
                result=result_text(result := item.get("result", {})),
                finished=time_text(result.get("time_stop")),
                failed=result.get("exit_status") not in (None, "completed"),
            )
            for i, item in enumerate(self._history)
        ]
        self._view.show_history(list(reversed(rows)))  # newest first

    def _on_status(self, event: StatusUpdated) -> None:
        self._status = event.status
        self._refresh_controls()
        self._view.show_loop(bool((event.status.get("plan_queue_mode") or {}).get("loop")))

    def _on_permissions(self, event: PermissionsKnown) -> None:
        self._allowed = event.allowed
        self._refresh_controls()
        if not event.allowed.read_queue:
            self._view.show_item_details(
                "The queue is not visible to this connection (it has no API key)."
            )

    def _refresh_controls(self) -> None:
        self._view.enable_controls(
            controls_for(self._status, self._allowed), has_queue=bool(self._items)
        )

    def _on_disconnected(self) -> None:
        self._running, self._items, self._history = None, [], []
        self._status, self._allowed = None, Permissions.full()
        self._view.show_queue([])
        self._view.show_history([])
        self._view.enable_controls(Controls(), has_queue=False)

    def _find(self, uid: str | None) -> JSON | None:
        candidates = [*self._items, *([self._running] if self._running else [])]
        return next((it for it in candidates if uid and it.get("item_uid") == uid), None)

    @staticmethod
    def _row(item: JSON, position: str, running: bool = False) -> QueueRow:
        return QueueRow(
            uid=item.get("item_uid", ""),
            position=position,
            title=item_title(item),
            parameters=parameters_text(item),
            user=item.get("user", ""),
            running=running,
        )
