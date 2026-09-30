"""Available plans: grouped by where they come from, with a filter box.

ScriptRunner's "Available scripts". Double-click opens the plan's source, as
double-clicking a script opens ScriptRunner's editor.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGroupBox, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from planrunner.controllers.plans import PlansHandlers
from planrunner.plan_groups import PlanGroup

_PLAN = Qt.ItemDataRole.UserRole


class PlanList:
    def __init__(self) -> None:
        self.widget = QGroupBox("Available plans")
        layout = QVBoxLayout(self.widget)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter plans…")
        self._filter.setClearButtonEnabled(True)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(12)
        layout.addWidget(self._filter)
        layout.addWidget(self._tree)

    def set_handlers(self, handlers: PlansHandlers) -> None:
        self._filter.textChanged.connect(handlers.on_filter_changed)
        self._tree.itemSelectionChanged.connect(lambda: self._selected(handlers))
        self._tree.itemDoubleClicked.connect(lambda item, _: self._activated(item, handlers))

    def show_plans(self, groups: list[PlanGroup], selected: str | None) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        bold = QFont()
        bold.setBold(True)
        for group in groups:
            header = QTreeWidgetItem([f"{group.title}  ({len(group.names)})"])
            header.setFont(0, bold)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(header)
            for name in group.names:
                item = QTreeWidgetItem([name])
                item.setData(0, _PLAN, name)
                header.addChild(item)
                if name == selected:
                    item.setSelected(True)
                    self._tree.setCurrentItem(item)
            header.setExpanded(True)
        self._tree.blockSignals(False)

    def names(self) -> list[str]:
        """All plan names shown (for tests)."""
        names: list[str] = []
        for g in range(self._tree.topLevelItemCount()):
            if (group := self._tree.topLevelItem(g)) is not None:
                names += [group.child(i).data(0, _PLAN) for i in range(group.childCount())]
        return names

    @staticmethod
    def _activated(item: QTreeWidgetItem, handlers: PlansHandlers) -> None:
        if name := item.data(0, _PLAN):
            handlers.on_plan_activated(name)

    def _selected(self, handlers: PlansHandlers) -> None:
        items = self._tree.selectedItems()
        if items and (name := items[0].data(0, _PLAN)):
            handlers.on_plan_selected(name)
