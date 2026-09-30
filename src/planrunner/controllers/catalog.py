"""The allowed plans and devices, loaded once and shared by every controller that needs them."""

from planrunner.controllers.commands import Commands
from planrunner.events import (
    AllowedChanged,
    CatalogCleared,
    CatalogUpdated,
    Connected,
    Disconnected,
    Notice,
    PermissionsKnown,
)
from planrunner.plan_params import Catalog, PlanSpec, describe_plan
from planrunner.protocols import JSON, EventBusLike
from planrunner.source_types import SourceAnnotations


class CatalogStore:
    """Loads ``plans_allowed`` + ``devices_allowed`` on connect and whenever they change.

    Publishes ``CatalogUpdated`` / ``CatalogCleared``; controllers also read the
    current catalog synchronously through ``plans``, ``catalog`` and ``spec``.
    """

    def __init__(self, *, commands: Commands, bus: EventBusLike,
                 source_types: SourceAnnotations | None = None) -> None:
        self._commands = commands
        self._bus = bus
        self._source_types = source_types
        self.plans: dict[str, JSON] = {}
        self.catalog = Catalog()
        self._may_read = True

        bus.subscribe(PermissionsKnown, self._on_permissions)
        bus.subscribe(Connected, lambda _: self.reload())
        bus.subscribe(AllowedChanged, lambda _: self.reload())
        bus.subscribe(Disconnected, lambda _: self._on_disconnected())

    def spec(self, name: str) -> PlanSpec | None:
        plan = self.plans.get(name)
        if plan is None:
            return None
        from_source = self._source_types.for_plan(plan) if self._source_types else None
        return describe_plan(plan, self.catalog, from_source)

    def reload(self) -> None:
        if not self._may_read:
            return

        def fetch(api) -> tuple[JSON, JSON]:
            return api.plans_allowed(reload=True), api.devices_allowed(reload=True)

        self._commands.send("Load plans", fetch, self._on_loaded, announce=False)

    def _on_loaded(self, replies: tuple[JSON, JSON]) -> None:
        plans_reply, devices_reply = replies
        self.plans = dict(plans_reply.get("plans_allowed", {}))
        self.catalog = Catalog.from_allowed(
            devices_reply.get("devices_allowed", {}), plans=self.plans
        )
        self._bus.publish(CatalogUpdated(dict(self.plans), self.catalog))
        self._bus.publish(Notice(f"Loaded {len(self.plans)} plans"))

    def _on_permissions(self, event: PermissionsKnown) -> None:
        self._may_read = event.allowed.read_resources
        if not self._may_read:
            self._clear(
                "This connection may not list plans (it has no API key). "
                "Connect with the beamline API key to build and queue plans."
            )

    def _on_disconnected(self) -> None:
        self._may_read = True  # the next connection's permissions decide again
        self._clear("Connect to a server to see its plans.")

    def _clear(self, reason: str) -> None:
        self.plans, self.catalog = {}, Catalog()
        self._bus.publish(CatalogCleared(reason))
