"""Which cameras in the running plan an operator can send an event trigger to.

A Phantom capture (and a Phantom fly scan, before its PandA fires) waits for an
EVENT trigger: the moment the operator, watching the live image, decides to keep.
The profile offers ``send_event_trigger(camera)`` for this; planrunner asks the
queueserver to run it in the background (``function_execute``), so the API key's
permissions apply and the queueserver records who triggered.

A camera qualifies when it is named in the running item's parameters and its
device tree has a ``send_software_trigger`` signal (hextools' ``PhantomIO``),
found from ``devices_allowed`` alone, like the area-detector test.
"""

from collections.abc import Iterator

from planrunner.device_tree import DeviceNode
from planrunner.plan_params import Catalog
from planrunner.protocols import JSON

TRIGGER_FUNCTION = "send_event_trigger"
_TRIGGER_SIGNAL = "send_software_trigger"


def trigger_targets(running_item: JSON | None, catalog: Catalog) -> tuple[str, ...]:
    """The cameras of ``running_item`` that take an event trigger, in parameter order."""
    if not running_item:
        return ()
    values = [*running_item.get("args", ()), *running_item.get("kwargs", {}).values()]
    found: list[str] = []
    for name in _strings(values):
        node = catalog.tree.get(name)
        if node is not None and _takes_trigger(node) and name not in found:
            found.append(name)
    return tuple(found)


def _takes_trigger(node: DeviceNode) -> bool:
    return any(n.name == _TRIGGER_SIGNAL for n in node.walk())


def _strings(value: object) -> Iterator[str]:
    match value:
        case str():
            yield value
        case list() | tuple():
            for item in value:
                yield from _strings(item)
        case dict():
            for item in value.values():
                yield from _strings(item)
        case _:
            return
