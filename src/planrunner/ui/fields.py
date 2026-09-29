"""One input widget per ``FieldKind``.

``make_field`` looks the kind up in a factory table, so supporting a new kind of
parameter means adding one class and one table entry.
"""

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Protocol

from planrunner.plan_params import FieldKind, FormValue, ParamSpec
from planrunner.ui.style import LIST_SELECT_BG, LIST_SELECT_FG


class FieldWidget(Protocol):
    @property
    def widget(self) -> tk.Widget: ...

    def get(self) -> FormValue: ...

    def set(self, value: FormValue) -> None: ...


class TextField:
    def __init__(self, parent: tk.Misc, spec: ParamSpec, width: int = 22) -> None:
        self._var = tk.StringVar()
        self._entry = ttk.Entry(parent, textvariable=self._var, width=width)

    @property
    def widget(self) -> tk.Widget:
        return self._entry

    def get(self) -> FormValue:
        return self._var.get()

    def set(self, value: FormValue) -> None:
        self._var.set(str(value))


class CheckField:
    def __init__(self, parent: tk.Misc, spec: ParamSpec) -> None:
        self._var = tk.BooleanVar()
        self._check = ttk.Checkbutton(parent, variable=self._var)

    @property
    def widget(self) -> tk.Widget:
        return self._check

    def get(self) -> FormValue:
        return self._var.get()

    def set(self, value: FormValue) -> None:
        self._var.set(bool(value))


class ChoiceField:
    """A drop-down. Read-only for a closed set; editable when choices are suggestions."""

    def __init__(self, parent: tk.Misc, spec: ParamSpec) -> None:
        self._var = tk.StringVar()
        choices = list(spec.choices)
        if not spec.required and not spec.choices_are_suggestions:
            choices.insert(0, "")  # lets the user go back to "use the default"
        self._combo = ttk.Combobox(
            parent,
            textvariable=self._var,
            values=choices,
            width=22,
            state="normal" if spec.choices_are_suggestions else "readonly",
        )

    @property
    def widget(self) -> tk.Widget:
        return self._combo

    def get(self) -> FormValue:
        return self._var.get()

    def set(self, value: FormValue) -> None:
        self._var.set(str(value))


class MultiChoiceField:
    """A short list where several names can be ticked."""

    def __init__(self, parent: tk.Misc, spec: ParamSpec) -> None:
        self._frame = ttk.Frame(parent)
        self._choices = list(spec.choices)
        self._list = tk.Listbox(
            self._frame,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            height=min(max(len(self._choices), 2), 6),
            width=24,
            selectbackground=LIST_SELECT_BG,
            selectforeground=LIST_SELECT_FG,
            activestyle="none",
        )
        for name in self._choices:
            self._list.insert(tk.END, name)
        self._list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if len(self._choices) > 6:
            scrollbar = ttk.Scrollbar(self._frame, orient="vertical", command=self._list.yview)
            self._list.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    @property
    def widget(self) -> tk.Widget:
        return self._frame

    def get(self) -> FormValue:
        return [self._choices[i] for i in self._list.curselection()]

    def set(self, value: FormValue) -> None:
        selected = set(value) if isinstance(value, list) else set()
        self._list.selection_clear(0, tk.END)
        for i, name in enumerate(self._choices):
            if name in selected:
                self._list.selection_set(i)


def _expression_field(parent: tk.Misc, spec: ParamSpec) -> FieldWidget:
    return ChoiceField(parent, spec) if spec.choices else TextField(parent, spec, width=30)


type FieldFactory = Callable[[tk.Misc, ParamSpec], FieldWidget]

DEFAULT_FACTORIES: Mapping[FieldKind, FieldFactory] = {
    FieldKind.INTEGER: TextField,
    FieldKind.FLOAT: TextField,
    FieldKind.STRING: TextField,
    FieldKind.BOOLEAN: CheckField,
    FieldKind.CHOICE: ChoiceField,
    FieldKind.MULTI_CHOICE: MultiChoiceField,
    FieldKind.EXPRESSION: _expression_field,
}


def make_field(
    parent: tk.Misc,
    spec: ParamSpec,
    factories: Mapping[FieldKind, FieldFactory] = DEFAULT_FACTORIES,
) -> FieldWidget:
    return factories[spec.field_kind](parent, spec)
