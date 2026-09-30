"""The read-only plan source viewer (ScriptRunner's editor window, without editing)."""

from typing import Protocol

from planrunner.controllers.catalog import CatalogStore
from planrunner.events import SourceRequested
from planrunner.protocols import Dialogs, EventSubscriber
from planrunner.sources import PlanSource, SourceFinder


class SourceView(Protocol):
    def show_source(self, title: str, source: PlanSource) -> None:
        """Open (or replace) a pane showing ``source``; up to two side by side."""
        ...


class SourceController:
    def __init__(
        self,
        *,
        view: SourceView,
        finder: SourceFinder,
        catalog: CatalogStore,
        bus: EventSubscriber,
        dialogs: Dialogs,
    ) -> None:
        self._view = view
        self._finder = finder
        self._catalog = catalog
        self._dialogs = dialogs
        bus.subscribe(SourceRequested, lambda event: self.show(event.plan_name))

    def show(self, name: str) -> None:
        plan = self._catalog.plans.get(name, {})
        module = plan.get("module")
        source = self._finder.find(name, module)
        if source is None:
            where = ", ".join(str(r) for r in self._finder.roots) or "no source folders set"
            self._dialogs.error(
                "Plan source",
                f"Could not find the source of '{name}' (module {module or '__main__'}) "
                f"on this machine.\nSearched: {where}.\n"
                "Add the profile collection or hextools checkout with --source PATH.",
            )
            return
        self._view.show_source(name, source)
