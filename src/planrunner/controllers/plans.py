"""Available plans and Plan parameters: pick a plan, fill it in, run it or schedule it.

The form always belongs to the plan selected in the list: when the server's plan
list changes (e.g. the environment opens), the form is rebuilt for the same plan,
or cleared if that plan is no longer offered.
"""

from dataclasses import dataclass, field
from typing import Protocol

from planrunner.controllers.catalog import CatalogStore
from planrunner.controllers.commands import Commands
from planrunner.controllers.run_control import RunControl
from planrunner.events import (
    CatalogCleared,
    CatalogUpdated,
    ItemAdded,
    PermissionsKnown,
    SourceRequested,
)
from planrunner.plan_groups import PlanGroup, group_plans
from planrunner.plan_params import (
    FormValue,
    PlanInputError,
    PlanSpec,
    build_item,
    name_conversion_warnings,
)
from planrunner.protocols import JSON, Dialogs, EventBusLike


@dataclass(frozen=True, slots=True)
class ScheduleOptions:
    """ScriptRunner's 'Iteration' and 'Position' fields."""

    iterations: int = 1
    position: int = -1
    """1-based queue position; -1 (or anything below 1) means the end of the queue."""

    def server_pos(self) -> int | str:
        return "back" if self.position < 1 else self.position - 1


class PlansHandlers(Protocol):
    def on_filter_changed(self, text: str) -> None: ...

    def on_plan_selected(self, name: str) -> None: ...

    def on_plan_activated(self, name: str) -> None:
        """Double-click: show the plan's source."""
        ...

    def on_run_now(self) -> None: ...

    def on_stop_run(self) -> None: ...

    def on_add_to_schedule(self) -> None: ...


class PlanListView(Protocol):
    def set_handlers(self, handlers: PlansHandlers) -> None: ...

    def show_plans(self, groups: list[PlanGroup], selected: str | None) -> None: ...


class PlanFormView(Protocol):
    def set_handlers(self, handlers: PlansHandlers) -> None: ...

    def show_plan(self, spec: PlanSpec, values: dict[str, FormValue]) -> None: ...

    def clear(self, message: str) -> None: ...

    def read_values(self) -> dict[str, FormValue]: ...

    def read_schedule_options(self) -> ScheduleOptions: ...

    def show_errors(self, errors: dict[str, str]) -> None: ...

    def enable_submit(self, schedule: bool, run_now: bool, stop: bool) -> None: ...


@dataclass(slots=True)
class _State:
    filter_text: str = ""
    current: PlanSpec | None = None
    remembered: dict[str, dict[str, FormValue]] = field(default_factory=dict)
    """Values typed into each plan's form, kept when switching plans (as ScriptRunner does)."""


class PlansController:
    def __init__(
        self,
        *,
        plan_list: PlanListView,
        form: PlanFormView,
        catalog: CatalogStore,
        commands: Commands,
        run_control: RunControl,
        bus: EventBusLike,
        dialogs: Dialogs,
    ) -> None:
        self._list = plan_list
        self._form = form
        self._catalog = catalog
        self._commands = commands
        self._run_control = run_control
        self._bus = bus
        self._dialogs = dialogs
        self._state = _State()

        plan_list.set_handlers(self)
        form.set_handlers(self)
        form.clear("Connect to a server to see its plans.")
        bus.subscribe(CatalogUpdated, lambda _: self._on_catalog())
        bus.subscribe(CatalogCleared, lambda event: self._on_cleared(event.reason))
        bus.subscribe(PermissionsKnown, lambda event: form.enable_submit(
            schedule=event.allowed.edit_queue, run_now=event.allowed.execute,
            stop=event.allowed.control_plan))

    # --- Handlers ---------------------------------------------------------------

    def on_filter_changed(self, text: str) -> None:
        self._state.filter_text = text
        self._show_list()

    def on_plan_selected(self, name: str) -> None:
        self._remember_current()
        self._show_plan(name)

    def on_plan_activated(self, name: str) -> None:
        self._bus.publish(SourceRequested(name))

    def on_run_now(self) -> None:
        if (item := self._build()) is None:
            return
        if self._dialogs.confirm("Run now", f"Run '{item['name']}' now, without scheduling it?"):
            self._commands.send(f"Run {item['name']}", lambda api: api.item_execute(item))

    def on_stop_run(self) -> None:
        self._run_control.stop_run()

    def on_add_to_schedule(self) -> None:
        if (item := self._build()) is None:
            return
        options = self._form.read_schedule_options()
        count = max(options.iterations, 1)
        label = f"{count} x {item['name']}" if count > 1 else item["name"]

        def added(reply: JSON) -> None:
            uids = [it.get("item_uid", "") for it in reply.get("items", [])]
            self._bus.publish(
                ItemAdded(tuple((uid, k, count) for k, uid in enumerate(uids, start=1)))
            )

        self._commands.send(
            f"Add {label} to schedule",
            lambda api: api.item_add_batch([item] * count, pos=options.server_pos()),
            on_success=added,
        )

    # --- Events -----------------------------------------------------------------

    def _on_catalog(self) -> None:
        current = self._state.current
        if current is not None and current.name in self._catalog.plans:
            self._remember_current()
            self._show_plan(current.name)
        else:
            self._state.current = None
            self._form.clear("Select a plan from the list.")
        self._show_list()

    def _on_cleared(self, reason: str) -> None:
        self._state.current = None
        self._list.show_plans([], None)
        self._form.clear(reason)

    # --- Internals --------------------------------------------------------------

    def _show_list(self) -> None:
        current = self._state.current.name if self._state.current else None
        self._list.show_plans(group_plans(self._catalog.plans, self._state.filter_text), current)

    def _show_plan(self, name: str) -> None:
        spec = self._catalog.spec(name)
        if spec is None:
            return
        self._state.current = spec
        defaults = {p.name: p.initial_value() for p in spec.params}
        remembered = {
            k: v for k, v in self._state.remembered.get(name, {}).items() if k in defaults
        }
        self._form.show_plan(spec, defaults | remembered)

    def _remember_current(self) -> None:
        if (spec := self._state.current) is not None:
            self._state.remembered[spec.name] = self._form.read_values()

    def _build(self) -> JSON | None:
        spec = self._state.current
        if spec is None:
            self._dialogs.error("Plan", "Select a plan first.")
            return None
        try:
            item = build_item(spec, self._form.read_values())
        except PlanInputError as ex:
            self._form.show_errors(ex.errors)
            return None
        self._form.show_errors({})
        if not confirm_name_conversions(self._dialogs, spec, item, self._catalog):
            return None
        return item


def confirm_name_conversions(dialogs: Dialogs, spec: PlanSpec, item: JSON,
                             catalog: CatalogStore) -> bool:
    """Ask before sending text the server would turn into a device; True to go ahead."""
    warnings = name_conversion_warnings(spec, item, catalog.catalog)
    if not warnings:
        return True
    lines = "\n".join(f"  {name}: {message}" for name, message in warnings.items())
    return dialogs.confirm(
        "Text that names a device",
        f"These values match device or plan names on the server:\n\n{lines}\n\n"
        "Because these parameters have no declared type, the server will replace the "
        "text with the device or plan object. Send anyway?",
    )
