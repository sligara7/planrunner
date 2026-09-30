"""The kinds of input field a plan parameter can have."""

from enum import StrEnum


class FieldKind(StrEnum):
    """Which widget to draw for a parameter."""

    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    STRING = "str"
    CHOICE = "choice"
    """Pick one name (a device, plan or enum value)."""
    MULTI_CHOICE = "multi"
    """Pick several names."""
    EXPRESSION = "expression"
    """A Python literal (number, list, dict, ...) or a bare device/plan name."""
