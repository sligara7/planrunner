"""The device tree the queueserver reports in ``devices_allowed``.

Each node has a class name, the readable/movable/flyable flags and its components;
a component is addressed by dotted path (``tomo_rot_axis.user_setpoint``), which the
queueserver's worker resolves to the live object.

The flags are coarse: legacy ophyd marks read-only signals (``EpicsSignalRO``)
"movable". Whether a signal can be written is therefore taken from its class name
where the class says so (``SignalR``, ``EpicsSignalRO`` are read-only).
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

_READ_ONLY_CLASSES = {"SignalR", "EpicsSignalRO", "SignalRO", "DerivedSignalR"}


@dataclass(frozen=True, slots=True)
class DeviceNode:
    path: str
    classname: str = ""
    readable: bool = False
    movable: bool = False
    flyable: bool = False
    children: tuple["DeviceNode", ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return self.path.rsplit(".", 1)[-1]

    @property
    def settable(self) -> bool:
        """Can be moved or written: movable and not a read-only signal class."""
        return self.movable and not self.read_only

    @property
    def read_only(self) -> bool:
        return self.classname in _READ_ONLY_CLASSES or self.classname.endswith("RO")

    @property
    def is_signal(self) -> bool:
        return "Signal" in self.classname and not self.children

    def walk(self) -> Iterator["DeviceNode"]:
        """This node and every descendant, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()


def parse_devices(devices_allowed: Mapping[str, Any], prefix: str = "") -> dict[str, DeviceNode]:
    """Top-level devices by name, each with its component tree."""
    nodes: dict[str, DeviceNode] = {}
    for name, info in sorted(devices_allowed.items()):
        path = f"{prefix}{name}"
        children = parse_devices(info.get("components") or {}, prefix=f"{path}.")
        nodes[name] = DeviceNode(
            path=path,
            classname=str(info.get("classname", "")),
            readable=bool(info.get("is_readable")),
            movable=bool(info.get("is_movable")),
            flyable=bool(info.get("is_flyable")),
            children=tuple(children.values()),
        )
    return nodes


def find(tree: Mapping[str, DeviceNode], path: str) -> DeviceNode | None:
    top, _, rest = path.partition(".")
    node = tree.get(top)
    for part in rest.split(".") if rest else ():
        if node is None:
            return None
        node = next((c for c in node.children if c.name == part), None)
    return node


# The areaDetector driver's own records, under the same attribute names in ophyd-async
# (ADBaseIO and every driver built on it) and legacy ophyd (CamBase).
_AREA_DETECTOR_DRIVER = frozenset({"acquire", "acquire_time", "image_mode", "array_counter"})


def is_area_detector(node: DeviceNode) -> bool:
    """Has an areaDetector driver among its components (a camera, not a PandA or a stage).

    Decided from the component tree, not class or device names, so a new camera
    class (e.g. hextools' Phantom, whose driver subclasses ``ADBaseIO``) is found too.
    """
    return any(_AREA_DETECTOR_DRIVER.issubset(c.name for c in child.children)
               for child in node.children)


def components(node: DeviceNode, settable_only: bool = False) -> list[str]:
    """Dotted paths under ``node`` (not the node itself), optionally only settable ones."""
    return [
        n.path for n in node.walk()
        if n is not node and (not settable_only or n.settable)
    ]
