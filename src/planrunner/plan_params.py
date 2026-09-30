"""Plan parameters: from a ``plans_allowed`` description to form fields and back.

Pure logic with no Tk or network imports:

* ``describe_plan`` turns one plan's description (plus the allowed devices and
  plans) into a ``PlanSpec``: one ``ParamSpec`` per parameter, saying which
  kind of field to draw, its choices, default and limits.
* ``build_item`` turns what the user entered back into a queue item
  ``{"item_type": "plan", "name", "args", "kwargs"}``, or raises
  ``PlanInputError`` naming every bad field.
* ``form_values`` does the reverse of ``build_item``, to edit a queued item.

A form value (``FormValue``) is what a field widget holds: text for most
fields, a bool for a checkbox, a list of names for a multi-select.
"""

import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from planrunner.arg_rows import Column, parse_rows, pattern_for
from planrunner.device_tree import DeviceNode, components, is_area_detector, parse_devices
from planrunner.field_kinds import FieldKind
from planrunner.protocols import JSON
from planrunner.type_guess import DeviceFilter, guess
from planrunner.type_strings import UNKNOWN, TypeShape, parse_type

type FormValue = str | bool | list[str]


class ParamKind(StrEnum):
    """``inspect.Parameter`` kinds, as the queueserver names them."""

    POSITIONAL_ONLY = "POSITIONAL_ONLY"
    POSITIONAL_OR_KEYWORD = "POSITIONAL_OR_KEYWORD"
    VAR_POSITIONAL = "VAR_POSITIONAL"
    KEYWORD_ONLY = "KEYWORD_ONLY"
    VAR_KEYWORD = "VAR_KEYWORD"


_NO_DEFAULT = object()
"""Marks a parameter that has no default."""
_OMIT = object()
"""Marks a field whose value should not be sent (the server default applies)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ParamSpec:
    name: str
    kind: ParamKind
    field_kind: FieldKind
    type_label: str
    """Short type shown next to the field, e.g. ``float``, ``readable``, ``list[device]``."""
    description: str = ""
    default: Any = _NO_DEFAULT
    allows_none: bool = False
    converts_names: bool = False
    """The server's worker replaces any string in this value that names a device or plan
    with the object itself (true for untyped parameters)."""
    choices: tuple[str, ...] = ()
    choices_are_suggestions: bool = False
    """True when the user may also type a value that is not in ``choices``."""
    minimum: float | None = None
    maximum: float | None = None
    choice_values: tuple[Any, ...] = ()
    """For ``Literal`` choices: the typed value behind each entry of ``choices``."""
    device_capability: str | None = None
    """For a device picker: 'movable', 'readable', 'detector', 'flyable', 'any', or
    'class' (the classes a source annotation names)."""
    component_choices: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """For a single-device picker: each device's components that may be chosen instead."""
    row_columns: tuple[Column, ...] = ()
    """For ``DEVICE_ROWS``: the repeating pattern of each row."""

    @property
    def has_default(self) -> bool:
        return self.default is not _NO_DEFAULT

    @property
    def is_variadic(self) -> bool:
        return self.kind in (ParamKind.VAR_POSITIONAL, ParamKind.VAR_KEYWORD)

    @property
    def required(self) -> bool:
        return not (self.has_default or self.is_variadic)

    def initial_value(self) -> FormValue:
        """What the field shows before the user edits it: the default, if any."""
        if not self.has_default or self.default is None:
            return False if self.field_kind is FieldKind.BOOLEAN else ""
        return to_form_value(self, self.default)


@dataclass(frozen=True, slots=True)
class PlanSpec:
    name: str
    description: str
    params: tuple[ParamSpec, ...]

    def param(self, name: str) -> ParamSpec:
        return next(p for p in self.params if p.name == name)


@dataclass(frozen=True, slots=True)
class Catalog:
    """What the server allows, as names grouped the way parameter types need them."""

    devices: tuple[str, ...] = ()
    detectors: tuple[str, ...] = ()
    """What a 'detector' parameter should offer: the area detectors (cameras); when the
    server has none, everything readable and not movable."""
    readable: tuple[str, ...] = ()
    movable: tuple[str, ...] = ()
    flyable: tuple[str, ...] = ()
    plans: tuple[str, ...] = ()
    tree: Mapping[str, DeviceNode] = field(default_factory=dict)
    """Each top-level device with its component tree."""

    @classmethod
    def from_allowed(cls, devices: Mapping[str, JSON], plans: Iterable[str]) -> Self:
        def names(flag: str | None = None) -> tuple[str, ...]:
            return tuple(sorted(n for n, d in devices.items() if flag is None or d.get(flag)))

        tree = parse_devices(devices)
        return cls(
            devices=names(),
            detectors=_detectors(devices, tree),
            readable=names("is_readable"),
            movable=names("is_movable"),
            flyable=names("is_flyable"),
            plans=tuple(sorted(plans)),
            tree=tree,
        )

    def builtin_choices(self, marker: str) -> tuple[str, ...] | None:
        """Names for a queueserver built-in type marker, or None if it is not one."""
        match marker:
            case "__DEVICE__":
                return self.devices
            case "__READABLE__":
                return self.readable
            case "__MOVABLE__":
                return self.movable
            case "__FLYABLE__":
                return self.flyable
            case "__PLAN__" | "__CALLABLE__":
                return self.plans
            case "__PLAN_OR_DEVICE__":
                return self.plans + self.devices
            case _:
                return None


class PlanInputError(ValueError):
    """Some fields hold values the plan cannot accept."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        self.errors = dict(errors)
        super().__init__("; ".join(f"{name}: {msg}" for name, msg in self.errors.items()))


# ------------------------------------------------------------------------------
#                       Description -> spec
# ------------------------------------------------------------------------------


def describe_plan(plan: JSON, catalog: Catalog,
                  source_types: Mapping[str, str] | None = None) -> PlanSpec:
    """``source_types``: annotations from the plan's local source (see ``source_types``),
    used for parameters the queueserver describes without a type."""
    return PlanSpec(
        name=plan["name"],
        description=plan.get("description", ""),
        params=tuple(
            _describe_param(p, catalog, plan["name"], (source_types or {}).get(p["name"]))
            for p in plan.get("parameters", ())
        ),
    )


def _describe_param(param: JSON, catalog: Catalog, plan_name: str = "",
                    source_type: str | None = None) -> ParamSpec:
    kind = ParamKind(param.get("kind", {}).get("name", ParamKind.POSITIONAL_OR_KEYWORD))
    annotation = param.get("annotation") or {}
    shape = parse_type(annotation.get("type"))
    default = _read_default(param)
    common: dict[str, Any] = {
        "name": param["name"],
        "kind": kind,
        "description": param.get("description", ""),
        "default": default,
        "allows_none": shape.allows_none or default is None,
        "minimum": _read_number(param.get("min")),
        "maximum": _read_number(param.get("max")),
        "converts_names": shape is UNKNOWN,
    }

    if kind is ParamKind.VAR_POSITIONAL and (columns := pattern_for(plan_name, param["name"])):
        return ParamSpec(
            field_kind=FieldKind.DEVICE_ROWS,
            type_label=", ".join(c.name for c in columns) + ", …",
            choices=catalog.movable,
            device_capability="movable",
            component_choices=_component_choices(
                FieldKind.CHOICE, "movable", catalog.movable, catalog),
            row_columns=columns,
            **common,
        )

    if kind in (ParamKind.VAR_POSITIONAL, ParamKind.VAR_KEYWORD):
        label = "*args" if kind is ParamKind.VAR_POSITIONAL else "**kwargs"
        return ParamSpec(field_kind=FieldKind.EXPRESSION, type_label=label, **common)

    if shape.literals and not shape.names:
        return ParamSpec(
            field_kind=FieldKind.MULTI_CHOICE if shape.is_list else FieldKind.CHOICE,
            type_label=_with_units("one of", shape),
            choices=tuple(v if isinstance(v, str) else repr(v) for v in shape.literals),
            choice_values=shape.literals,
            **common,
        )

    if choices := _choices_for(shape, annotation, catalog):
        names, suggestions_only = choices
        kind_of_field = FieldKind.MULTI_CHOICE if shape.is_list else FieldKind.CHOICE
        if suggestions_only:
            kind_of_field = FieldKind.EXPRESSION
        capability = _capability(shape)
        return ParamSpec(
            field_kind=kind_of_field,
            type_label=_label(shape),
            choices=names,
            choices_are_suggestions=suggestions_only,
            device_capability=capability,
            component_choices=_component_choices(kind_of_field, capability, names, catalog),
            **common,
        )

    if not shape.is_list and (simple := _simple_field(shape)) is not None:
        return ParamSpec(field_kind=simple, type_label=_with_units(_label(shape), shape), **common)

    if shape is UNKNOWN:
        if source_type and (typed := _source_typed_param(source_type, catalog, common)):
            return typed
        return _guessed_param(param["name"], default, catalog, common)

    return ParamSpec(field_kind=FieldKind.EXPRESSION, type_label=_label(shape), **common)


def _source_typed_param(source_type: str, catalog: Catalog,
                        common: dict[str, Any]) -> ParamSpec | None:
    """Devices whose class the source annotation names, e.g. ``list[KinetixDetector]``.

    None when the annotation names no class an allowed device has (then it is guessed).
    """
    shape = parse_type(source_type)
    devices = tuple(name for name, node in catalog.tree.items()
                    if node.classname in shape.names)
    if not devices:
        return None
    return ParamSpec(
        field_kind=FieldKind.MULTI_CHOICE if shape.is_list else FieldKind.CHOICE,
        type_label=f"{source_type} (from source)",
        choices=devices,
        device_capability="class",
        **{**common, "allows_none": common["allows_none"] or shape.allows_none},
    )


def _guessed_param(name: str, default: Any, catalog: Catalog, common: dict[str, Any]) -> ParamSpec:
    """An untyped parameter: see ``planrunner.type_guess``."""
    g = guess(name, default, has_default=default is not _NO_DEFAULT)
    if g.devices is None:
        return ParamSpec(field_kind=g.field_kind, type_label=g.label, **common)
    choices = {
        DeviceFilter.DETECTOR: catalog.detectors,
        DeviceFilter.READABLE: catalog.readable,
        DeviceFilter.MOVABLE: catalog.movable,
        DeviceFilter.FLYABLE: catalog.flyable,
        DeviceFilter.ANY: catalog.devices,
    }[g.devices]
    capability = g.devices.value
    return ParamSpec(
        field_kind=g.field_kind,
        type_label=g.label,
        choices=choices,
        # A guess may be wrong: a single device may also be typed in.
        choices_are_suggestions=g.field_kind is FieldKind.CHOICE,
        device_capability=capability,
        component_choices=_component_choices(g.field_kind, capability, choices, catalog),
        **common,
    )


_MARKER_CAPABILITY = {
    "__MOVABLE__": "movable",
    "__DEVICE__": "any",
    "__READABLE__": "readable",
    "__FLYABLE__": "flyable",
}


def _capability(shape: TypeShape) -> str | None:
    found = {_MARKER_CAPABILITY[n] for n in shape.names if n in _MARKER_CAPABILITY}
    return found.pop() if len(found) == 1 else None


def _detectors(devices: Mapping[str, JSON], tree: Mapping[str, DeviceNode]) -> tuple[str, ...]:
    if cameras := tuple(sorted(n for n, node in tree.items() if is_area_detector(node))):
        return cameras
    return tuple(sorted(n for n, d in devices.items()
                        if d.get("is_readable") and not d.get("is_movable")))


def _component_choices(
    kind: FieldKind, capability: str | None, devices: tuple[str, ...], catalog: Catalog
) -> dict[str, tuple[str, ...]]:
    """Components a single-device picker may offer: settable ones for movable, all for any."""
    if kind is not FieldKind.CHOICE or capability not in ("movable", "any"):
        return {}
    offered = {}
    for name in devices:
        node = catalog.tree.get(name)
        if node is not None and (paths := components(node, settable_only=capability == "movable")):
            offered[name] = tuple(paths)
    return offered


def _with_units(label: str, shape: TypeShape) -> str:
    units = ", ".join(str(m) for m in shape.metadata if isinstance(m, str))
    return f"{label}, {units}" if units else label


def _simple_field(shape: TypeShape) -> FieldKind | None:
    match sorted(shape.names):
        case ["int"]:
            return FieldKind.INTEGER
        case ["float"] | ["float", "int"]:
            return FieldKind.FLOAT
        case ["bool"]:
            return FieldKind.BOOLEAN
        case ["str"]:
            return FieldKind.STRING
        case _:
            return None


def _choices_for(
    shape: TypeShape, annotation: JSON, catalog: Catalog
) -> tuple[tuple[str, ...], bool] | None:
    """The names a parameter may take, and whether other values are allowed too."""
    groups: dict[str, list[str]] = {}
    for key in ("devices", "plans", "enums"):
        groups.update(annotation.get(key) or {})

    names: list[str] = []
    other_types = False
    for type_name in shape.names:
        if type_name in groups:
            names.extend(groups[type_name])
        elif (builtin := catalog.builtin_choices(type_name)) is not None:
            names.extend(builtin)
        else:
            other_types = True
    if not names:
        return None
    return tuple(dict.fromkeys(names)), other_types


def _label(shape: TypeShape) -> str:
    def short(name: str) -> str:
        return name.strip("_").lower() if name.startswith("__") else name

    inner = " | ".join(sorted(short(n) for n in shape.names)) or "any"
    label = f"list[{inner}]" if shape.is_list else inner
    return f"{label} | None" if shape.allows_none else label


def _read_default(param: JSON) -> Any:
    if "default" not in param:
        return _NO_DEFAULT
    try:
        return ast.literal_eval(param["default"])
    except (ValueError, SyntaxError):
        return param["default"]


def _read_number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------
#                       Form values -> queue item
# ------------------------------------------------------------------------------


def build_item(plan: PlanSpec, values: Mapping[str, FormValue]) -> JSON:
    """Build the queue item for ``plan`` from the form's values.

    Empty fields and fields left at their default are omitted, so the server's
    default applies and queued items stay short. Raises ``PlanInputError``.
    """
    parsed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for spec in plan.params:
        try:
            parsed[spec.name] = parse_form_value(spec, values.get(spec.name, ""))
        except ValueError as ex:
            errors[spec.name] = str(ex)
    if errors:
        raise PlanInputError(errors)

    # Filling *args forces every parameter before it to be passed positionally:
    # scan(detectors, *args) called as scan(motor, 0, 1, detectors=...) would bind the
    # motor to 'detectors'.
    varargs = next((p for p in plan.params if p.kind is ParamKind.VAR_POSITIONAL), None)
    positional_before = varargs is not None and bool(parsed.get(varargs.name)) and (
        parsed.get(varargs.name) is not _OMIT)
    call = _Call()
    before_varargs = True
    for spec in plan.params:
        if spec is varargs:
            before_varargs = False
        value = parsed[spec.name]
        if positional_before and before_varargs and spec.kind in (
            ParamKind.POSITIONAL_ONLY, ParamKind.POSITIONAL_OR_KEYWORD
        ):
            call.args.append(spec.default if value is _OMIT else value)
            continue
        try:
            call.add(spec, value)
        except ValueError as ex:
            errors[spec.name] = str(ex)
    if errors:
        raise PlanInputError(errors)

    args, kwargs = call.args, call.kwargs
    item: JSON = {"item_type": "plan", "name": plan.name}
    if args:
        item["args"] = args
    if kwargs:
        item["kwargs"] = kwargs
    return item



@dataclass(slots=True)
class _Call:
    """Accumulates parsed values into the plan's ``args`` and ``kwargs``."""

    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    skipped_positional: str | None = None

    def add(self, spec: ParamSpec, value: Any) -> None:
        """Place one value; raises ``ValueError`` when it cannot go where it must."""
        if value is _OMIT:
            if spec.kind is ParamKind.POSITIONAL_ONLY:
                self.skipped_positional = spec.name
            return
        match spec.kind:
            case ParamKind.POSITIONAL_ONLY:
                if self.skipped_positional:
                    raise ValueError(f"needs '{self.skipped_positional}' to be set first")
                self.args.append(value)
            case ParamKind.VAR_POSITIONAL:
                if not isinstance(value, list | tuple):
                    raise ValueError("enter a list, e.g. [1, 2]")
                self.args.extend(value)
            case ParamKind.VAR_KEYWORD:
                if not isinstance(value, dict):
                    raise ValueError("enter a dict, e.g. {'key': 1}")
                self.kwargs.update(value)
            case _:
                self.kwargs[spec.name] = value


def parse_form_value(spec: ParamSpec, raw: FormValue) -> Any:
    """One field's value as the plan should receive it, or ``_OMIT``. Raises ``ValueError``."""
    if _is_empty(raw) and spec.field_kind is not FieldKind.BOOLEAN:
        if spec.has_default or spec.is_variadic:
            return _OMIT
        if spec.allows_none:
            return None
        raise ValueError("required")

    if isinstance(raw, str) and raw.strip() == "None" and spec.allows_none:
        value = None
    else:
        value = _convert(spec, raw)
        _check_range(spec, value)

    if spec.has_default and value == spec.default and type(value) is type(spec.default):
        return _OMIT
    return value


def _convert(spec: ParamSpec, raw: FormValue) -> Any:
    match spec.field_kind:
        case FieldKind.BOOLEAN:
            return bool(raw)
        case FieldKind.MULTI_CHOICE:
            names = raw if isinstance(raw, list) else _split_names(str(raw))
            _check_choices(spec, names)
            return names
        case FieldKind.CHOICE:
            _check_choices(spec, [str(raw)])
            if spec.choice_values:
                return spec.choice_values[spec.choices.index(str(raw))]
            return str(raw)
        case FieldKind.INTEGER:
            return _parse_number(int, str(raw), "a whole number")
        case FieldKind.FLOAT:
            return _parse_number(float, str(raw), "a number")
        case FieldKind.STRING:
            return str(raw)
        case FieldKind.EXPRESSION:
            return _parse_expression(str(raw))
        case FieldKind.DEVICE_ROWS:
            def device_ok(name: str) -> bool:
                return name in spec.choices or name in spec.component_choices.get(
                    name.split(".", maxsplit=1)[0], ())

            return parse_rows(str(raw), spec.row_columns, device_ok)


def _parse_number[N: (int, float)](kind: type[N], text: str, what: str) -> N:
    try:
        return kind(text.strip())
    except ValueError:
        raise ValueError(f"'{text}' is not {what}") from None


def _parse_expression(text: str) -> Any:
    """A Python literal, or a bare (dotted) name such as a device, passed as a string."""
    text = text.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        if all(part.isidentifier() for part in text.split(".")):
            return text
        raise ValueError(f"'{text}' is not a valid value") from None


def _check_choices(spec: ParamSpec, names: list[str]) -> None:
    if spec.choices_are_suggestions:
        return
    def allowed(name: str) -> bool:
        top = name.split(".", maxsplit=1)[0]
        return name in spec.choices or name in spec.component_choices.get(top, ())

    if unknown := [n for n in names if not allowed(n)]:
        raise ValueError(f"not allowed: {', '.join(unknown)}")


def _check_range(spec: ParamSpec, value: Any) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return
    if spec.minimum is not None and value < spec.minimum:
        raise ValueError(f"must be >= {spec.minimum:g}")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"must be <= {spec.maximum:g}")


def _split_names(text: str) -> list[str]:
    text = text.strip().strip("[]")
    return [n.strip().strip("'\"") for n in text.split(",") if n.strip()]


def _is_empty(raw: FormValue) -> bool:
    if isinstance(raw, bool):
        return False
    if isinstance(raw, str):
        return not raw.strip()
    return not raw


# ------------------------------------------------------------------------------
#                       Queue item -> form values
# ------------------------------------------------------------------------------


def form_values(plan: PlanSpec, item: JSON) -> dict[str, FormValue]:
    """The form values that reproduce ``item``: the inverse of ``build_item``."""
    bound = _bind(plan, list(item.get("args", ())), dict(item.get("kwargs", {})))
    values = {spec.name: spec.initial_value() for spec in plan.params}
    for spec in plan.params:
        if spec.name in bound:
            values[spec.name] = to_form_value(spec, bound[spec.name])
    return values


def to_form_value(spec: ParamSpec, value: Any) -> FormValue:
    match spec.field_kind:
        case FieldKind.BOOLEAN:
            return bool(value)
        case FieldKind.MULTI_CHOICE:
            items = value if isinstance(value, list | tuple) else [value]
            return [str(v) for v in items]
        case FieldKind.CHOICE if spec.choice_values:
            if value in spec.choice_values:
                return spec.choices[spec.choice_values.index(value)]
            return "" if value is None else str(value)
        case FieldKind.STRING | FieldKind.CHOICE:
            return "" if value is None else str(value)
        case FieldKind.INTEGER | FieldKind.FLOAT:
            return "" if value is None else repr(value)
        case FieldKind.EXPRESSION:
            if isinstance(value, str) and all(p.isidentifier() for p in value.split(".")):
                return value  # a device or plan name: show it bare
            return repr(value)
        case FieldKind.DEVICE_ROWS:
            return repr(list(value))


def _bind(plan: PlanSpec, args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    positional = []
    for p in plan.params:  # only parameters before *args can take positional values
        if p.kind is ParamKind.VAR_POSITIONAL:
            break
        if p.kind in (ParamKind.POSITIONAL_ONLY, ParamKind.POSITIONAL_OR_KEYWORD):
            positional.append(p)
    for spec, value in zip(positional, args, strict=False):
        bound[spec.name] = value
    extra_args = args[len(positional):]
    extra_kwargs = {}
    names = {p.name for p in plan.params if not p.is_variadic}
    for name, value in kwargs.items():
        if name in names:
            bound[name] = value
        else:
            extra_kwargs[name] = value
    for spec in plan.params:
        if spec.kind is ParamKind.VAR_POSITIONAL and extra_args:
            bound[spec.name] = extra_args
        elif spec.kind is ParamKind.VAR_KEYWORD and extra_kwargs:
            bound[spec.name] = extra_kwargs
    return bound



# ------------------------------------------------------------------------------
#                       Text that the server will turn into a device
# ------------------------------------------------------------------------------


def name_conversion_warnings(plan: PlanSpec, item: JSON, catalog: Catalog) -> dict[str, str]:
    """Parameters whose text values the server will silently replace with a device or plan.

    For an untyped parameter the queueserver's worker converts every string, at any
    depth, that matches an allowed device or plan name (or a dotted path under one).
    Device pickers are exempt: there a device is what was meant.
    """
    names = set(catalog.devices) | set(catalog.plans)
    bound = _bind(plan, list(item.get("args", ())), dict(item.get("kwargs", {})))
    warnings: dict[str, str] = {}
    for spec in plan.params:
        if not spec.converts_names or spec.choices or spec.name not in bound:
            continue
        if matches := sorted(set(_named_strings(bound[spec.name], names))):
            listed = ", ".join(f"'{m}'" for m in matches)
            what = "is a device or plan name" if len(matches) == 1 else "are device or plan names"
            warnings[spec.name] = (
                f"{listed} {what}: the server will pass the device or plan itself, not the text"
            )
    return warnings


def _named_strings(value: Any, names: set[str]) -> list[str]:
    match value:
        case str() if value in names or value.split(".")[0] in names:
            return [value]
        case list() | tuple():
            return [s for v in value for s in _named_strings(v, names)]
        case dict():
            return [s for v in value.values() for s in _named_strings(v, names)]
        case _:
            return []
