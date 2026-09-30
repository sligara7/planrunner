"""One input widget per ``FieldKind``, and the parameter grid built from them.

``ParamGrid`` lays parameters out as ScriptRunner does, one row each:
name | [type] | input | help. The Plan parameters panel and Task Details both use it.
Supporting a new kind of parameter means one widget class and one table entry.
"""

import ast
from collections.abc import Callable, Mapping
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from planrunner.plan_params import FieldKind, FormValue, ParamSpec


class FieldWidget(Protocol):
    @property
    def widget(self) -> QWidget: ...

    def get(self) -> FormValue: ...

    def set(self, value: FormValue) -> None: ...


class TextField:
    def __init__(self, spec: ParamSpec, width: int = 180) -> None:
        self._edit = QLineEdit()
        self._edit.setMinimumWidth(width)
        if spec.allows_none and not spec.required:
            self._edit.setPlaceholderText("default")

    @property
    def widget(self) -> QWidget:
        return self._edit

    def get(self) -> FormValue:
        return self._edit.text()

    def set(self, value: FormValue) -> None:
        self._edit.setText(str(value))


class CheckField:
    def __init__(self, spec: ParamSpec) -> None:
        self._box = QCheckBox()

    @property
    def widget(self) -> QWidget:
        return self._box

    def get(self) -> FormValue:
        return self._box.isChecked()

    def set(self, value: FormValue) -> None:
        self._box.setChecked(bool(value))


class ChoiceField:
    """A drop-down: a closed set, or editable when the choices are only suggestions."""

    def __init__(self, spec: ParamSpec) -> None:
        self._combo = QComboBox()
        self._combo.setMinimumWidth(180)
        self._combo.setEditable(spec.choices_are_suggestions)
        if not spec.required and not spec.choices_are_suggestions:
            self._combo.addItem("")  # back to "use the default"
        self._combo.addItems(list(spec.choices))

    @property
    def widget(self) -> QWidget:
        return self._combo

    def get(self) -> FormValue:
        return self._combo.currentText()

    def set(self, value: FormValue) -> None:
        text = str(value)
        index = self._combo.findText(text)
        if index >= 0:
            self._combo.setCurrentIndex(index)
        elif self._combo.isEditable():
            self._combo.setEditText(text)


class DevicePathField:
    """A device, and optionally one of its components: ``tomo_rot_axis`` or
    ``tomo_rot_axis.user_setpoint``. The component list follows the chosen device."""

    WHOLE_DEVICE = "(whole device)"

    def __init__(self, spec: ParamSpec) -> None:
        self._components = spec.component_choices
        self.widget_ = QWidget()
        layout = QHBoxLayout(self.widget_)
        layout.setContentsMargins(0, 0, 0, 0)
        self._device = ChoiceField(spec)
        self._component = QComboBox()
        self._component.setMinimumWidth(200)
        layout.addWidget(self._device.widget)
        layout.addWidget(self._component)
        self._device_combo().currentTextChanged.connect(self._fill_components)
        self._fill_components(self._device_combo().currentText())

    @property
    def widget(self) -> QWidget:
        return self.widget_

    def get(self) -> FormValue:
        device = str(self._device.get())
        component = self._component.currentText()
        if not device or component in ("", self.WHOLE_DEVICE):
            return device
        return f"{device}.{component}"

    def set(self, value: FormValue) -> None:
        device, _, component = str(value).partition(".")
        self._device.set(device)
        self._fill_components(device)
        index = self._component.findText(component) if component else 0
        self._component.setCurrentIndex(max(index, 0))

    def _device_combo(self) -> QComboBox:
        return self._device.widget  # type: ignore[return-value]

    def _fill_components(self, device: str) -> None:
        prefix = f"{device}."
        paths = self._components.get(device, ())
        self._component.blockSignals(True)
        self._component.clear()
        self._component.addItem(self.WHOLE_DEVICE)
        self._component.addItems([p.removeprefix(prefix) for p in paths])
        self._component.setEnabled(bool(paths))
        self._component.blockSignals(False)


class MultiChoiceField:
    """A short list of names, each with a checkbox."""

    def __init__(self, spec: ParamSpec) -> None:
        self._list = QListWidget()
        for name in spec.choices:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._list.addItem(item)
        rows = min(max(len(spec.choices), 2), 6)
        self._list.setFixedHeight(rows * self._list.sizeHintForRow(0) + 6)
        self._list.setMinimumWidth(180)

    @property
    def widget(self) -> QWidget:
        return self._list

    def get(self) -> FormValue:
        return [
            self._list.item(i).text()
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set(self, value: FormValue) -> None:
        chosen = set(value) if isinstance(value, list) else set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            checked = item.text() in chosen
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)


class DeviceRowsField:
    """One row per motor for mv / scan / grid_scan-style ``*args``: a device (or component)
    and the pattern's values, with rows added and removed by the operator."""

    def __init__(self, spec: ParamSpec) -> None:
        self._spec = spec
        self.widget_ = QWidget()
        outer = QVBoxLayout(self.widget_)
        outer.setContentsMargins(0, 0, 0, 0)
        self._rows_box = QVBoxLayout()
        outer.addLayout(self._rows_box)
        add = QPushButton(f"+ Add {spec.row_columns[0].name}")
        add.clicked.connect(lambda: self._add_row())  # noqa: PLW0108 - drop Qt's 'checked'
        outer.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        self._rows: list[tuple[QWidget, DevicePathField, list[QLineEdit]]] = []
        self._add_row()

    @property
    def widget(self) -> QWidget:
        return self.widget_

    def get(self) -> FormValue:
        values: list[object] = []
        for _, device, edits in self._rows:
            name = str(device.get())
            texts = [e.text().strip() for e in edits]
            if not name and not any(texts):
                continue  # an empty row
            values.append(name)
            values += [_literal_or_text(t) for t in texts]
        return repr(values) if values else ""

    def set(self, value: FormValue) -> None:
        for row, _, _ in list(self._rows):
            self._remove_row(row)
        try:
            flat = ast.literal_eval(str(value)) if value else []
        except (ValueError, SyntaxError):
            flat = []
        width = len(self._spec.row_columns)
        for start in range(0, len(flat) - width + 1, width):
            chunk = flat[start:start + width]
            self._add_row(str(chunk[0]), [repr(v) for v in chunk[1:]])
        if not self._rows:
            self._add_row()

    def _add_row(self, device: str = "", values: list[str] | None = None) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        picker = DevicePathField(self._spec)
        picker.set(device)
        layout.addWidget(picker.widget)
        edits = []
        for i, column in enumerate(self._spec.row_columns[1:]):
            edit = QLineEdit(values[i] if values and i < len(values) else "")
            edit.setPlaceholderText("[0, 1, 2]" if column.kind == "positions" else column.name)
            edit.setFixedWidth(110 if column.kind != "positions" else 160)
            layout.addWidget(edit)
            edits.append(edit)
        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        remove.clicked.connect(lambda: self._remove_row(row))
        layout.addWidget(remove)
        layout.addStretch(1)
        self._rows_box.addWidget(row)
        self._rows.append((row, picker, edits))

    def _remove_row(self, row: QWidget) -> None:
        self._rows = [r for r in self._rows if r[0] is not row]
        row.setParent(None)
        row.deleteLater()


def _literal_or_text(text: str) -> object:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _expression_field(spec: ParamSpec) -> FieldWidget:
    return ChoiceField(spec) if spec.choices else TextField(spec, width=240)


def _choice_field(spec: ParamSpec) -> FieldWidget:
    return DevicePathField(spec) if spec.component_choices else ChoiceField(spec)


type FieldFactory = Callable[[ParamSpec], FieldWidget]

DEFAULT_FACTORIES: Mapping[FieldKind, FieldFactory] = {
    FieldKind.INTEGER: TextField,
    FieldKind.FLOAT: TextField,
    FieldKind.STRING: TextField,
    FieldKind.BOOLEAN: CheckField,
    FieldKind.CHOICE: _choice_field,
    FieldKind.MULTI_CHOICE: MultiChoiceField,
    FieldKind.EXPRESSION: _expression_field,
    FieldKind.DEVICE_ROWS: DeviceRowsField,
}


class ParamGrid:
    """name | [type] | input | help, one row per parameter."""

    def __init__(self, factories: Mapping[FieldKind, FieldFactory] = DEFAULT_FACTORIES) -> None:
        self._factories = factories
        self.widget = QWidget()
        self._layout = QGridLayout(self.widget)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(14)
        self._layout.setColumnStretch(3, 1)
        self._fields: dict[str, FieldWidget] = {}
        self._help: dict[str, tuple[QLabel, str]] = {}

    def show(self, params: tuple[ParamSpec, ...], values: Mapping[str, FormValue]) -> None:
        self.clear()
        for row, param in enumerate(params):
            name = QLabel(f"{param.name} *" if param.required else param.name)
            if param.required:
                name.setStyleSheet("font-weight: bold;")
            kind = QLabel(f"[{param.type_label}]")
            kind.setProperty("role", "type")
            field = self._factories[param.field_kind](param)
            field.set(values.get(param.name, param.initial_value()))
            help_text = _help_text(param)
            help_label = QLabel(help_text)
            help_label.setProperty("role", "help")
            help_label.setWordWrap(True)
            top = Qt.AlignmentFlag.AlignTop
            self._layout.addWidget(name, row, 0, top)
            self._layout.addWidget(kind, row, 1, top)
            self._layout.addWidget(field.widget, row, 2, top)
            self._layout.addWidget(help_label, row, 3, top)
            self._fields[param.name] = field
            self._help[param.name] = (help_label, help_text)

    def clear(self) -> None:
        while (item := self._layout.takeAt(0)) is not None:
            if (w := item.widget()) is not None:
                w.deleteLater()
        self._fields.clear()
        self._help.clear()

    def values(self) -> dict[str, FormValue]:
        return {name: field.get() for name, field in self._fields.items()}

    def field(self, name: str) -> FieldWidget:
        return self._fields[name]

    def set_read_only(self, read_only: bool) -> None:
        for field in self._fields.values():
            field.widget.setEnabled(not read_only)

    def show_errors(self, errors: Mapping[str, str]) -> None:
        for name, (label, help_text) in self._help.items():
            error = errors.get(name)
            label.setText(f"⚠ {error}" if error else help_text)
            label.setProperty("role", "error" if error else "help")
            label.style().unpolish(label)
            label.style().polish(label)


def _help_text(param: ParamSpec) -> str:
    text = " ".join(param.description.split())
    if param.minimum is not None or param.maximum is not None:
        low = f"{param.minimum:g}" if param.minimum is not None else "…"
        high = f"{param.maximum:g}" if param.maximum is not None else "…"
        text = f"{text} (range {low} to {high})".strip()
    return text
