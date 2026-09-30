"""Device -> value rows for Bluesky plans whose ``*args`` repeat a pattern.

``mv(motor1, 5, motor2, 10)``, ``scan(dets, motor, start, stop, ..., num=5)``: the
queueserver can only describe these ``*args`` as "anything", so the patterns are
known here instead, from bluesky's own signatures. A plan listed here gets one
form row per motor instead of a free-text list.
"""

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ColumnKind(StrEnum):
    DEVICE = "device"
    NUMBER = "number"
    COUNT = "count"
    POSITIONS = "positions"


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: ColumnKind


_MOVE = (Column("motor", ColumnKind.DEVICE), Column("position", ColumnKind.NUMBER))
_MOVE_BY = (Column("motor", ColumnKind.DEVICE), Column("delta", ColumnKind.NUMBER))
_LINE = (Column("motor", ColumnKind.DEVICE), Column("start", ColumnKind.NUMBER),
         Column("stop", ColumnKind.NUMBER))
_GRID = (*_LINE, Column("num", ColumnKind.COUNT))
_LIST = (Column("motor", ColumnKind.DEVICE), Column("positions", ColumnKind.POSITIONS))

PATTERNS: dict[str, tuple[Column, ...]] = {
    "mv": _MOVE, "mov": _MOVE,
    "mvr": _MOVE_BY, "movr": _MOVE_BY,
    "scan": _LINE, "rel_scan": _LINE, "relative_scan": _LINE,
    "inner_product_scan": _LINE, "relative_inner_product_scan": _LINE,
    "grid_scan": _GRID, "rel_grid_scan": _GRID,
    "outer_product_scan": _GRID, "relative_outer_product_scan": _GRID,
    "list_scan": _LIST, "rel_list_scan": _LIST, "relative_list_scan": _LIST,
    "list_grid_scan": _LIST, "rel_list_grid_scan": _LIST,
}


def pattern_for(plan_name: str, param_name: str) -> tuple[Column, ...] | None:
    return PATTERNS.get(plan_name) if param_name == "args" else None


def parse_rows(text: str, columns: tuple[Column, ...],
               device_ok: Any = lambda name: True) -> list[Any]:
    """The flat ``*args`` list from its text form; raises ``ValueError`` naming the problem.

    ``device_ok(name)`` decides whether a device (or component path) is allowed.
    """
    try:
        values = ast.literal_eval(text) if text.strip() else []
    except (ValueError, SyntaxError):
        raise ValueError("could not read the rows") from None
    if not isinstance(values, list | tuple):
        raise ValueError("expected rows of " + ", ".join(c.name for c in columns))
    width = len(columns)
    if len(values) % width:
        raise ValueError(f"each row needs {width} values: " + ", ".join(c.name for c in columns))
    for start in range(0, len(values), width):
        row = start // width + 1
        for column, value in zip(columns, values[start:start + width], strict=True):
            _check(column, value, row, device_ok)
    return list(values)


def _check(column: Column, value: Any, row: int, device_ok: Any) -> None:
    where = f"row {row}, {column.name}"
    match column.kind:
        case ColumnKind.DEVICE:
            if not isinstance(value, str) or not device_ok(value):
                raise ValueError(f"{where}: '{value}' is not an allowed movable device")
        case ColumnKind.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{where}: '{value}' is not a number")
        case ColumnKind.COUNT:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{where}: '{value}' is not a whole number >= 1")
        case ColumnKind.POSITIONS:
            if not isinstance(value, list | tuple) or not all(
                isinstance(v, int | float) and not isinstance(v, bool) for v in value
            ):
                raise ValueError(f"{where}: expected a list of numbers, e.g. [0, 1.5, 3]")


def split_rows(values: list[Any], columns: tuple[Column, ...]) -> list[list[Any]]:
    width = len(columns)
    return [list(values[i:i + width]) for i in range(0, len(values) - width + 1, width)]
