"""Right panel: the selected plan's parameters as input fields.

Same layout as ScriptRunner's "Script parameters" panel: one row per parameter
(name, [type], input, help), with the run/queue buttons underneath.
"""

import tkinter as tk
from collections.abc import Mapping
from tkinter import ttk

from planrunner.controllers.plans import PlansHandlers, QueueOptions
from planrunner.plan_params import FieldKind, FormValue, PlanSpec
from planrunner.ui.fields import DEFAULT_FACTORIES, FieldFactory, FieldWidget, make_field
from planrunner.ui.style import PARAM_FONT_SIZE
from planrunner.ui.widgets import ScrollableFrame, set_enabled


class PlanForm:
    def __init__(
        self, parent: tk.Misc, factories: Mapping[FieldKind, FieldFactory] = DEFAULT_FACTORIES
    ) -> None:
        self._factories = factories
        self.frame = ttk.LabelFrame(parent, text="   Plan parameters", padding=0)
        self._scroll = ScrollableFrame(self.frame)
        self._fields: dict[str, FieldWidget] = {}
        self._help: dict[str, tuple[ttk.Label, str]] = {}

        buttons = ttk.Frame(self.frame)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=(0, 5))
        self._scroll.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._normal_buttons = ttk.Frame(buttons)
        self._run_now = ttk.Button(self._normal_buttons, text="Run now", width=10)
        self._run_now.pack(side=tk.LEFT)
        self._reset = ttk.Button(self._normal_buttons, text="Reset", width=8)
        self._reset.pack(side=tk.LEFT, padx=5)
        self._add = ttk.Button(self._normal_buttons, text="Add to queue", width=14)
        self._add.pack(side=tk.RIGHT)
        self._position = tk.StringVar()
        ttk.Entry(self._normal_buttons, textvariable=self._position, width=4).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Label(self._normal_buttons, text="Position:").pack(side=tk.RIGHT)
        self._repeat = tk.StringVar(value="1")
        ttk.Spinbox(self._normal_buttons, from_=1, to=999, textvariable=self._repeat,
                    width=4).pack(side=tk.RIGHT, padx=5)
        ttk.Label(self._normal_buttons, text="Repeat:").pack(side=tk.RIGHT)

        self._edit_buttons = ttk.Frame(buttons)
        self._edit_label = ttk.Label(self._edit_buttons, style="Title.TLabel")
        self._edit_label.pack(side=tk.LEFT)
        self._cancel_edit = ttk.Button(self._edit_buttons, text="Cancel", width=10)
        self._cancel_edit.pack(side=tk.RIGHT)
        self._save_edit = ttk.Button(self._edit_buttons, text="Save changes", width=14)
        self._save_edit.pack(side=tk.RIGHT, padx=5)

        self.set_edit_mode(None)

    # --- PlanFormView -----------------------------------------------------------

    def set_handlers(self, handlers: PlansHandlers) -> None:
        self._run_now.configure(command=handlers.on_run_now)
        self._reset.configure(command=handlers.on_reset_form)
        self._add.configure(command=handlers.on_add_to_queue)
        self._save_edit.configure(command=handlers.on_save_edit)
        self._cancel_edit.configure(command=handlers.on_cancel_edit)

    def show_plan(self, spec: PlanSpec, values: dict[str, FormValue]) -> None:
        self._scroll.clear()
        self._fields.clear()
        self._help.clear()
        content = self._scroll.content
        content.grid_columnconfigure(3, weight=1)

        ttk.Label(content, text=spec.name, style="Title.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=5
        )
        if spec.description:
            ttk.Label(content, text=spec.description.strip(), style="Help.TLabel",
                      justify="left", wraplength=700).grid(
                row=1, column=0, columnspan=4, sticky="w", padx=5, pady=(0, 8)
            )

        for row, param in enumerate(spec.params, start=2):
            name = f"{param.name} *" if param.required else param.name
            style = "Required.TLabel" if param.required else "Param.TLabel"
            ttk.Label(content, text=name, style=style, width=18, anchor="w").grid(
                row=row, column=0, sticky="nw", padx=2, pady=2
            )
            ttk.Label(content, text=f"[{param.type_label}]", style="Type.TLabel").grid(
                row=row, column=1, sticky="nw", padx=2, pady=2
            )
            field = make_field(content, param, self._factories)
            field.set(values.get(param.name, param.initial_value()))
            field.widget.grid(row=row, column=2, sticky="nw", padx=2, pady=2)
            help_text = _help_text(param.description, param.minimum, param.maximum)
            help_label = ttk.Label(content, text=help_text, style="Help.TLabel",
                                   justify="left", wraplength=450)
            help_label.grid(row=row, column=3, sticky="nw", padx=5, pady=2)
            self._fields[param.name] = field
            self._help[param.name] = (help_label, help_text)

        if not spec.params:
            ttk.Label(content, text="This plan takes no parameters.",
                      font=("", PARAM_FONT_SIZE)).grid(row=2, column=0, columnspan=4, sticky="w")

    def clear(self, message: str) -> None:
        self._scroll.clear()
        self._fields.clear()
        self._help.clear()
        ttk.Label(self._scroll.content, text=message, style="Help.TLabel").grid(
            row=0, column=0, sticky="w", padx=5, pady=5
        )

    def read_values(self) -> dict[str, FormValue]:
        return {name: field.get() for name, field in self._fields.items()}

    def read_queue_options(self) -> QueueOptions:
        try:
            repeat = max(int(self._repeat.get()), 1)
        except ValueError:
            repeat = 1
        position_text = self._position.get().strip()
        try:
            position = int(position_text) if position_text else None
        except ValueError:
            position = None
        if position is not None and position < 1:
            position = None
        return QueueOptions(repeat=repeat, position=position)

    def show_errors(self, errors: dict[str, str]) -> None:
        for name, (label, help_text) in self._help.items():
            if name in errors:
                label.configure(text=f"⚠ {errors[name]}", style="Error.TLabel")
            else:
                label.configure(text=help_text, style="Help.TLabel")

    def enable_submit(self, add: bool, run_now: bool) -> None:
        set_enabled(self._add, add)
        set_enabled(self._save_edit, add)
        set_enabled(self._run_now, run_now)

    def set_edit_mode(self, editing: str | None) -> None:
        if editing is None:
            self._edit_buttons.pack_forget()
            self._normal_buttons.pack(fill=tk.X)
        else:
            self._normal_buttons.pack_forget()
            self._edit_label.configure(text=f"Editing queued item: {editing}")
            self._edit_buttons.pack(fill=tk.X)


def _help_text(description: str, minimum: float | None, maximum: float | None) -> str:
    text = " ".join(description.split())
    if minimum is not None or maximum is not None:
        low = f"{minimum:g}" if minimum is not None else "…"
        high = f"{maximum:g}" if maximum is not None else "…"
        text = f"{text} (range {low} to {high})".strip()
    return text
