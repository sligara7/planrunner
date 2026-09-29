"""The plan list and the plan parameter form: pick a plan, fill it in, queue it."""

from dataclasses import dataclass, field
from typing import Protocol

from planrunner.controllers.commands import Commands
from planrunner.events import (
    AllowedChanged,
    Connected,
    Disconnected,
    EditItemRequested,
    Notice,
)
from planrunner.plan_params import (
    Catalog,
    FormValue,
    PlanInputError,
    PlanSpec,
    build_item,
    describe_plan,
    form_values,
)
from planrunner.protocols import JSON, Dialogs, EventPublisher, EventSubscriber


@dataclass(frozen=True, slots=True)
class QueueOptions:
    repeat: int = 1
    position: int | None = None
    """1-based queue position to insert at; ``None`` appends to the back."""

    def server_pos(self) -> int | str:
        return "back" if self.position is None else max(self.position - 1, 0)


class PlansHandlers(Protocol):
    def on_filter_changed(self, text: str) -> None: ...

    def on_plan_selected(self, name: str) -> None: ...

    def on_add_to_queue(self) -> None: ...

    def on_run_now(self) -> None: ...

    def on_reset_form(self) -> None: ...

    def on_save_edit(self) -> None: ...

    def on_cancel_edit(self) -> None: ...


class PlanListView(Protocol):
    def set_handlers(self, handlers: PlansHandlers) -> None: ...

    def show_plans(self, names: list[str], selected: str | None) -> None: ...


class PlanFormView(Protocol):
    def set_handlers(self, handlers: PlansHandlers) -> None: ...

    def show_plan(self, spec: PlanSpec, values: dict[str, FormValue]) -> None: ...

    def clear(self, message: str) -> None: ...

    def read_values(self) -> dict[str, FormValue]: ...

    def read_queue_options(self) -> QueueOptions: ...

    def show_errors(self, errors: dict[str, str]) -> None: ...

    def set_edit_mode(self, editing: str | None) -> None:
        """Show the 'save changes' buttons for the named item, or the normal ones for None."""
        ...


@dataclass(slots=True)
class _State:
    plans: dict[str, JSON] = field(default_factory=dict)
    catalog: Catalog = field(default_factory=Catalog)
    filter_text: str = ""
    current: PlanSpec | None = None
    remembered: dict[str, dict[str, FormValue]] = field(default_factory=dict)
    """Values typed into each plan's form, kept when switching plans (as ScriptRunner does)."""
    editing: JSON | None = None
    pending_edit: JSON | None = None
    """An item to edit that arrived before the plans were loaded."""


class PlansController:
    def __init__(
        self,
        *,
        plan_list: PlanListView,
        form: PlanFormView,
        commands: Commands,
        bus: EventSubscriber,
        publisher: EventPublisher,
        dialogs: Dialogs,
    ) -> None:
        self._list = plan_list
        self._form = form
        self._commands = commands
        self._publish = publisher.publish
        self._dialogs = dialogs
        self._state = _State()

        plan_list.set_handlers(self)
        form.set_handlers(self)
        form.clear("Connect to a server to see its plans.")
        bus.subscribe(Connected, lambda _: self._load_allowed())
        bus.subscribe(AllowedChanged, lambda _: self._load_allowed())
        bus.subscribe(Disconnected, lambda _: self._reset())
        bus.subscribe(EditItemRequested, lambda event: self._start_edit(event.item))

    # --- Handlers ---------------------------------------------------------------

    def on_filter_changed(self, text: str) -> None:
        self._state.filter_text = text.strip().lower()
        self._show_list()

    def on_plan_selected(self, name: str) -> None:
        if self._state.editing is not None:
            self.on_cancel_edit()
        self._remember_current()
        self._show_plan(name)

    def on_add_to_queue(self) -> None:
        if (item := self._build()) is None:
            return
        options = self._form.read_queue_options()
        items = [item] * max(options.repeat, 1)
        count = f"{len(items)} x " if len(items) > 1 else ""
        self._commands.send(
            f"Add {count}{item['name']} to queue",
            lambda api: api.item_add_batch(items, pos=options.server_pos()),
        )

    def on_run_now(self) -> None:
        if (item := self._build()) is None:
            return
        if self._dialogs.confirm("Run now", f"Run '{item['name']}' now, without queueing it?"):
            self._commands.send(f"Run {item['name']}", lambda api: api.item_execute(item))

    def on_reset_form(self) -> None:
        if (spec := self._state.current) is not None:
            self._state.remembered.pop(spec.name, None)
            self._form.show_plan(spec, {p.name: p.initial_value() for p in spec.params})

    def on_save_edit(self) -> None:
        editing = self._state.editing
        if editing is None or (item := self._build()) is None:
            return
        item = {**editing, "args": item.get("args", []), "kwargs": item.get("kwargs", {})}
        self._commands.send(
            f"Update {item['name']}",
            lambda api: api.item_update(item),
            on_success=lambda _: self._finish_edit(),
        )

    def on_cancel_edit(self) -> None:
        self._finish_edit()

    # --- Internals --------------------------------------------------------------

    def _load_allowed(self) -> None:
        def fetch(api) -> tuple[JSON, JSON]:
            return api.plans_allowed(reload=True), api.devices_allowed(reload=True)

        self._commands.send("Load plans", fetch, self._on_allowed, announce=False)

    def _on_allowed(self, replies: tuple[JSON, JSON]) -> None:
        plans_reply, devices_reply = replies
        state = self._state
        state.plans = dict(plans_reply.get("plans_allowed", {}))
        state.catalog = Catalog.from_allowed(
            devices_reply.get("devices_allowed", {}), plans=state.plans
        )
        self._publish(Notice(f"Loaded {len(state.plans)} plans"))
        current = state.current.name if state.current else None
        self._show_list()
        if current in state.plans:
            self._show_plan(current)
        if state.pending_edit is not None:
            self._start_edit(state.pending_edit)

    def _show_list(self) -> None:
        text = self._state.filter_text
        names = sorted(n for n in self._state.plans if text in n.lower())
        current = self._state.current.name if self._state.current else None
        self._list.show_plans(names, current)

    def _show_plan(self, name: str, values: dict[str, FormValue] | None = None) -> None:
        if name not in self._state.plans:
            return
        spec = describe_plan(self._state.plans[name], self._state.catalog)
        self._state.current = spec
        if values is None:
            defaults = {p.name: p.initial_value() for p in spec.params}
            values = defaults | self._state.remembered.get(name, {})
        self._form.show_plan(spec, values)

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
        return item

    def _start_edit(self, item: JSON) -> None:
        state = self._state
        if not state.plans:
            state.pending_edit = item
            return
        state.pending_edit = None
        name = item.get("name", "")
        if name not in state.plans:
            self._dialogs.error("Edit", f"'{name}' is not an allowed plan on this server.")
            return
        self._remember_current()
        state.editing = item
        spec = describe_plan(state.plans[name], state.catalog)
        self._show_plan(name, form_values(spec, item))
        self._list.show_plans(sorted(n for n in state.plans if state.filter_text in n.lower()),
                              name)
        self._form.set_edit_mode(name)

    def _finish_edit(self) -> None:
        self._state.editing = None
        self._form.set_edit_mode(None)
        if (spec := self._state.current) is not None:
            self._show_plan(spec.name)

    def _reset(self) -> None:
        self._state = _State(remembered=self._state.remembered)
        self._list.show_plans([], None)
        self._form.clear("Connect to a server to see its plans.")
