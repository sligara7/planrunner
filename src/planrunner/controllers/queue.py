"""The scheduler: ScriptRunner's scheduler, backed by the queueserver's queue.

One table lists finished runs (from the server's history), the running item and
the pending items, each with a Status. Task Details shows the selected item and
edits a pending one in place. "Iteration" on Run queue repeats the whole queue;
"Add sleep" queues whichever sleep plan the server allows.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from planrunner.controllers.catalog import CatalogStore
from planrunner.controllers.commands import Commands
from planrunner.controllers.plans import confirm_name_conversions
from planrunner.controllers.run_control import RunControl
from planrunner.events import (
    Disconnected,
    HistoryUpdated,
    ItemAdded,
    PermissionsKnown,
    QueueUpdated,
    SourceRequested,
    StatusUpdated,
)
from planrunner.permissions import Permissions
from planrunner.plan_params import FormValue, PlanInputError, PlanSpec, build_item, form_values
from planrunner.protocols import JSON, Dialogs, EventBusLike
from planrunner.status_text import Controls, controls_for, item_details, item_title, parameters_text

SLEEP_PLANS = ("sleep_for_secs", "sleep")
"""Plans 'Add sleep' can queue, in order of preference (HEX's own first)."""
FINISHED_SHOWN = 50

_EXIT_STATUS = {
    "completed": "Done",
    "failed": "Failed",
    "aborted": "Aborted",
    "stopped": "Stopped",
    "halted": "Halted",
}


class RowState(StrEnum):
    DONE = "done"
    FAILED = "failed"
    RUNNING = "running"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    uid: str
    number: int
    iteration: str
    title: str
    details: str
    status: str
    state: RowState


class SchedulerHandlers(Protocol):
    def on_run_queue(self, iterations: int) -> None: ...

    def on_pause(self) -> None: ...

    def on_resume(self) -> None: ...

    def on_stop(self) -> None: ...

    def on_clear(self) -> None: ...

    def on_add_sleep(self, seconds: float, position: int) -> None: ...

    def on_row_selected(self, uid: str | None) -> None: ...

    def on_edit_task(self) -> None: ...

    def on_save_task(self) -> None: ...

    def on_delete_task(self) -> None: ...

    def on_move(self, uid: str, offset: int) -> None: ...

    def on_duplicate(self, uid: str) -> None: ...

    def on_view_source(self, uid: str) -> None: ...

    # The "More" menu
    def on_pause_now(self) -> None: ...

    def on_stop_after_current(self) -> None: ...

    def on_cancel_stop(self) -> None: ...

    def on_abort(self) -> None: ...

    def on_halt(self) -> None: ...

    def on_loop_changed(self, loop: bool) -> None: ...


class SchedulerView(Protocol):
    def set_handlers(self, handlers: SchedulerHandlers) -> None: ...

    def show_rows(self, rows: list[ScheduleRow]) -> None: ...

    def show_task_form(self, title: str, spec: PlanSpec, values: dict[str, FormValue]) -> None:
        """Task Details for a plan item: its parameters, read-only until editing starts."""
        ...

    def show_task_text(self, title: str, text: str) -> None: ...

    def set_task_editing(self, editing: bool, can_edit: bool) -> None: ...

    def read_task_values(self) -> dict[str, FormValue]: ...

    def show_task_errors(self, errors: dict[str, str]) -> None: ...

    def enable_controls(self, controls: Controls, has_pending: bool, can_sleep: bool) -> None: ...

    def show_loop(self, loop: bool) -> None: ...

    def reveal(self) -> None:
        """Show the scheduler if it is hidden (ScriptRunner does on 'Add to schedule')."""
        ...


class QueueController:
    def __init__(
        self,
        *,
        view: SchedulerView,
        catalog: CatalogStore,
        commands: Commands,
        run_control: RunControl,
        bus: EventBusLike,
        dialogs: Dialogs,
    ) -> None:
        self._view = view
        self._catalog = catalog
        self._commands = commands
        self._run_control = run_control
        self._bus = bus
        self._dialogs = dialogs
        self._running: JSON | None = None
        self._pending: list[JSON] = []
        self._finished: list[JSON] = []
        self._iterations: dict[str, tuple[int, int]] = {}
        self._selected: str | None = None
        self._editing = False
        self._status: JSON | None = None
        self._allowed = Permissions.full()

        view.set_handlers(self)
        self._refresh_controls()
        bus.subscribe(QueueUpdated, self._on_queue)
        bus.subscribe(HistoryUpdated, self._on_history)
        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(PermissionsKnown, self._on_permissions)
        bus.subscribe(ItemAdded, self._on_item_added)
        bus.subscribe(Disconnected, lambda _: self._on_disconnected())

    # --- Scheduler row ----------------------------------------------------------

    def on_run_queue(self, iterations: int) -> None:
        repeats = max(iterations, 1) - 1
        if repeats and self._pending:
            copies = [_copy(item) for item in self._pending] * repeats
            self._commands.send(
                f"Repeat the queue {iterations} times",
                lambda api: api.item_add_batch(copies),
                on_success=lambda _: self._start(),
            )
        else:
            self._start()

    def on_pause(self) -> None:
        self._commands.send("Pause at next checkpoint", lambda api: api.re_pause("deferred"))

    def on_resume(self) -> None:
        self._commands.send("Resume", lambda api: api.re_resume())

    def on_stop(self) -> None:
        self._run_control.stop_run()

    def on_clear(self) -> None:
        if self._pending and self._dialogs.confirm(
            "Clear", f"Remove all {len(self._pending)} pending items from the queue?"
        ):
            self._commands.send("Clear queue", lambda api: api.queue_clear())

    def on_add_sleep(self, seconds: float, position: int) -> None:
        item = self._sleep_item(seconds)
        if item is None:
            self._dialogs.error(
                "Add sleep",
                f"This server allows no sleep plan ({' or '.join(SLEEP_PLANS)}), "
                "so a sleep cannot be scheduled.",
            )
            return
        pos: int | str = "back" if position < 1 else position - 1
        self._commands.send(f"Add sleep {seconds:g} s", lambda api: api.item_add_batch(
            [item], pos=pos), on_success=lambda _: self._view.reveal())

    # --- Task Details -----------------------------------------------------------

    def on_row_selected(self, uid: str | None) -> None:
        self._selected, self._editing = uid, False
        self._show_selected()

    def on_edit_task(self) -> None:
        if self._selected_pending() is not None:
            self._editing = True
            self._view.set_task_editing(True, can_edit=True)

    def on_save_task(self) -> None:
        item = self._selected_pending()
        spec = self._catalog.spec(item.get("name", "")) if item else None
        if item is None or spec is None:
            return
        try:
            built = build_item(spec, self._view.read_task_values())
        except PlanInputError as ex:
            self._view.show_task_errors(ex.errors)
            return
        if not confirm_name_conversions(self._dialogs, spec, built, self._catalog):
            return
        updated = {**item, "args": built.get("args", []), "kwargs": built.get("kwargs", {})}
        self._commands.send(f"Save {item_title(item)}", lambda api: api.item_update(updated),
                            on_success=lambda _: self._stop_editing())

    def on_delete_task(self) -> None:
        item = self._selected_pending()
        if item is not None and self._dialogs.confirm(
            "Delete", f"Remove '{item_title(item)}' from the queue?"
        ):
            uid = item["item_uid"]
            self._commands.send(f"Delete {item_title(item)}",
                                lambda api: api.item_remove(uid=uid))

    # --- Row context menu ---------------------------------------------------------

    def on_move(self, uid: str, offset: int) -> None:
        index = next((i for i, it in enumerate(self._pending) if it.get("item_uid") == uid), None)
        if index is not None and 0 <= index + offset < len(self._pending):
            destination = index + offset
            self._commands.send("Move item", lambda api: api.item_move(
                uid=uid, pos_dest=destination), announce=False)

    def on_duplicate(self, uid: str) -> None:
        if (item := self._find(uid)) is not None:
            self._commands.send(f"Duplicate {item_title(item)}",
                                lambda api: api.item_add_batch([_copy(item)]))

    def on_view_source(self, uid: str) -> None:
        if (item := self._find(uid)) is not None:
            self._bus.publish(SourceRequested(item.get("name", "")))

    # --- The "More" menu ------------------------------------------------------------

    def on_pause_now(self) -> None:
        self._commands.send("Pause now", lambda api: api.re_pause("immediate"))

    def on_stop_after_current(self) -> None:
        self._commands.send("Stop after current plan", lambda api: api.queue_stop())

    def on_cancel_stop(self) -> None:
        self._commands.send("Cancel stop", lambda api: api.queue_stop_cancel())

    def on_abort(self) -> None:
        if self._dialogs.confirm("Abort", "Abort the paused plan? Its run is marked aborted."):
            self._commands.send("Abort", lambda api: api.re_abort())

    def on_halt(self) -> None:
        if self._dialogs.confirm(
            "Halt", "Halt the paused plan immediately, without cleanup? Use only in emergencies."
        ):
            self._commands.send("Halt", lambda api: api.re_halt())

    def on_loop_changed(self, loop: bool) -> None:
        self._commands.send(f"Loop queue {'on' if loop else 'off'}",
                            lambda api: api.queue_mode_set(loop=loop))

    # --- Events -------------------------------------------------------------------

    def _on_queue(self, event: QueueUpdated) -> None:
        self._running, self._pending = event.running_item, list(event.items)
        self._show_rows()
        self._refresh_controls()

    def _on_history(self, event: HistoryUpdated) -> None:
        self._finished = list(event.items)[-FINISHED_SHOWN:]
        self._show_rows()

    def _on_status(self, event: StatusUpdated) -> None:
        self._status = event.status
        self._refresh_controls()
        self._view.show_loop(bool((event.status.get("plan_queue_mode") or {}).get("loop")))

    def _on_permissions(self, event: PermissionsKnown) -> None:
        self._allowed = event.allowed
        self._refresh_controls()
        if not event.allowed.read_queue:
            self._view.show_task_text(
                "Queue not visible", "This connection may not see the queue (it has no API key)."
            )

    def _on_item_added(self, event: ItemAdded) -> None:
        for uid, k, n in event.copies:
            if uid:
                self._iterations[uid] = (k, n)
        self._view.reveal()

    def _on_disconnected(self) -> None:
        self._running, self._pending, self._finished = None, [], []
        self._status, self._allowed, self._selected = None, Permissions.full(), None
        self._view.show_rows([])
        self._view.show_task_text("", "")
        self._refresh_controls()

    # --- Internals ----------------------------------------------------------------

    def _start(self) -> None:
        self._commands.send("Run queue", lambda api: api.queue_start())

    def _show_rows(self) -> None:
        rows: list[ScheduleRow] = []
        for item in self._finished:
            result = item.get("result") or {}
            exit_status = result.get("exit_status", "")
            state = RowState.DONE if exit_status == "completed" else RowState.FAILED
            rows.append(self._row(item, len(rows) + 1,
                                  _EXIT_STATUS.get(exit_status, exit_status.title()), state))
        if self._running:
            paused = self._run_control.paused
            rows.append(self._row(self._running, len(rows) + 1,
                                  "Paused" if paused else "Running...", RowState.RUNNING))
        for item in self._pending:
            rows.append(self._row(item, len(rows) + 1, "Pending", RowState.PENDING))
        self._view.show_rows(rows)
        if self._selected and self._find(self._selected) is None:
            self._selected = None
            self._view.show_task_text("", "")

    def _row(self, item: JSON, number: int, status: str, state: RowState) -> ScheduleRow:
        uid = item.get("item_uid", "")
        k, n = self._iterations.get(uid, (1, 1))
        return ScheduleRow(
            uid=uid,
            number=number,
            iteration=f"{k}/{n}" if n > 1 else "1",
            title=item_title(item),
            details=parameters_text(item),
            status=status,
            state=state,
        )

    def _show_selected(self) -> None:
        item = self._find(self._selected)
        if item is None:
            self._view.show_task_text("", "")
            return
        pending = item in self._pending
        spec = self._catalog.spec(item.get("name", "")) if pending else None
        if spec is not None:
            self._view.show_task_form(item_title(item), spec, form_values(spec, item))
        else:
            self._view.show_task_text(item_title(item), item_details(item))
        self._view.set_task_editing(False, can_edit=spec is not None and self._allowed.edit_queue)

    def _stop_editing(self) -> None:
        self._editing = False
        self._view.set_task_editing(False, can_edit=self._allowed.edit_queue)

    def _selected_pending(self) -> JSON | None:
        return next((it for it in self._pending if it.get("item_uid") == self._selected), None)

    def _find(self, uid: str | None) -> JSON | None:
        if not uid:
            return None
        everything = [*self._finished, *([self._running] if self._running else []),
                      *self._pending]
        return next((it for it in everything if it.get("item_uid") == uid), None)

    def _sleep_item(self, seconds: float) -> JSON | None:
        for name in SLEEP_PLANS:
            spec = self._catalog.spec(name)
            if spec is None:
                continue
            first = next((p for p in spec.params if not p.is_variadic), None)
            if first is None:
                continue
            try:
                return build_item(spec, {first.name: repr(float(seconds))})
            except PlanInputError:
                continue
        return None

    def _refresh_controls(self) -> None:
        can_sleep = self._allowed.edit_queue and any(n in self._catalog.plans for n in SLEEP_PLANS)
        self._view.enable_controls(controls_for(self._status, self._allowed),
                                   has_pending=bool(self._pending), can_sleep=can_sleep)


def _copy(item: JSON) -> JSON:
    """A queue item without the server-assigned fields, ready to add again."""
    return {k: v for k, v in item.items() if k not in ("item_uid", "result", "user", "user_group")}
