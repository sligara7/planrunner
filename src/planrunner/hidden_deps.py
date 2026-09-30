"""Devices a plan uses without taking them as parameters, found in its source.

No queueserver description shows these: a plan body that names a device the
profile defines (``detector = germ_detector``), or looks one up at run time
(hextools' ``ensure_available(Shutter, fe_shutter=...)``,
``get_obj_from_ipython_ns("dclm", DCLM)``). Found by reading the plan's local
source, so only what is written plainly is found.
"""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class How(StrEnum):
    GLOBAL = "uses the profile's device directly"
    LOOKUP_IF_NOT_PASSED = "looks it up in the namespace when the parameter is not given"
    LOOKUP = "looks it up in the namespace"


@dataclass(frozen=True, slots=True)
class HiddenDependency:
    device: str
    how: How
    line: int
    """Line within the plan's source text (1 = its first line)."""


def hidden_dependencies(source: str, device_names: Iterable[str]) -> list[HiddenDependency]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    function = next((n for n in tree.body
                     if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)), None)
    if function is None:
        return []
    devices = set(device_names)
    local = _parameters(function) | _assigned(function)
    found: dict[tuple[str, How], int] = {}

    for node in ast.walk(function):
        match node:
            case ast.Name(id=name, ctx=ast.Load()) if name in devices and name not in local:
                found.setdefault((name, How.GLOBAL), node.lineno)
            case ast.Call(func=func) if _call_name(func) == "ensure_available":
                for keyword in node.keywords:
                    if keyword.arg:
                        found.setdefault((keyword.arg, How.LOOKUP_IF_NOT_PASSED), node.lineno)
            case ast.Call(func=func, args=[ast.Constant(value=str() as name), *_]) if (
                _call_name(func) == "get_obj_from_ipython_ns"
            ):
                found.setdefault((name, How.LOOKUP), node.lineno)
    return sorted((HiddenDependency(d, h, line) for (d, h), line in found.items()),
                  key=lambda dep: (dep.line, dep.device))


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = function.args
    names = [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    names += [p.arg for p in (a.vararg, a.kwarg) if p is not None]
    return set(names)


def _assigned(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def _call_name(func: ast.expr) -> str:
    match func:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case _:
            return ""
