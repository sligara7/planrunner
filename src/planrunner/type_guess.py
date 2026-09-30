"""Guess what an UNTYPED plan parameter takes, from its name and default.

Most HEX profile plans declare no types (e.g. ``count_germ(count_time, num=1,
detector=None, md=None)``), so the queueserver can only report names and defaults.
Offering device names for every such parameter put devices in number fields;
instead a device picker is offered only when the name says it is a device, and
simple types come from the default value or Bluesky naming conventions.

A guess is always labelled as one (``float?``). The real fix is for plans to
declare their types, which makes guessing unnecessary.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from planrunner.field_kinds import FieldKind


class DeviceFilter(StrEnum):
    DETECTOR = "detector"
    """Readable but not movable: excludes motors and settable command signals."""
    READABLE = "readable"
    MOVABLE = "movable"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class Guess:
    field_kind: FieldKind
    label: str
    devices: DeviceFilter | None = None
    """Offer these devices (only for device-like names)."""


_READABLE_WORDS = {"detector", "detectors", "det", "dets", "camera", "cameras", "cam", "panda"}
_MOVABLE_WORDS = {"motor", "motors", "stage", "axis", "positioner", "shutter", "shutters"}
_DEVICE_WORDS = {"device", "devices", "signal", "signals"}
_PLURAL_DEVICE_WORDS = {"detectors", "dets", "cameras", "motors", "shutters", "devices",
                        "signals"}
_COUNT_WORDS = {"num", "number", "n", "count", "counts", "repetitions", "iterations",
                "images", "projections", "steps", "points", "scans", "id", "moves"}
_REAL_WORDS = {"time", "exposure", "period", "delay", "seconds", "secs", "deg", "degrees",
               "angle", "start", "stop", "step", "offset", "position", "energy", "width",
               "speed", "gap", "velocity", "range", "size"}


def guess(name: str, default: Any, has_default: bool) -> Guess:
    words = set(name.lower().split("_"))

    if has_default and isinstance(default, bool):
        return Guess(FieldKind.BOOLEAN, "bool?")
    if name == "md" or name.endswith("_md"):
        return Guess(FieldKind.EXPRESSION, "dict?")

    if devices := _device_filter(words):
        plural = bool(words & _PLURAL_DEVICE_WORDS)
        kind = FieldKind.MULTI_CHOICE if plural else FieldKind.CHOICE
        return Guess(kind, f"list[{devices.value}]?" if plural else f"{devices.value}?", devices)

    if has_default and isinstance(default, int):
        counting = bool(words & _COUNT_WORDS) and not words & _REAL_WORDS
        return Guess(FieldKind.INTEGER, "int?") if counting else Guess(FieldKind.FLOAT, "float?")
    if has_default and isinstance(default, float):
        return Guess(FieldKind.FLOAT, "float?")
    if has_default and isinstance(default, str):
        return Guess(FieldKind.STRING, "str?")

    if words & _REAL_WORDS:
        return Guess(FieldKind.FLOAT, "float?")
    if words & _COUNT_WORDS:
        return Guess(FieldKind.INTEGER, "int?")
    return Guess(FieldKind.EXPRESSION, "any")


def _device_filter(words: set[str]) -> DeviceFilter | None:
    if words & _READABLE_WORDS:
        return DeviceFilter.DETECTOR
    if words & _MOVABLE_WORDS:
        return DeviceFilter.MOVABLE
    if words & _DEVICE_WORDS:
        return DeviceFilter.ANY
    return None
