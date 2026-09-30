"""Parameter types read from a plan's local source, where the queueserver drops them.

The queueserver keeps an annotation only if it can rebuild it from ``typing``,
``collections`` and ``bluesky`` names, so ``detectors: list[KinetixDetector |
PhantomDetector]`` reaches clients as an untyped ``detectors``. The class names are
still in the source, and ``devices_allowed`` gives each device's class name, so a
client that has the source can offer just the devices of those classes.

Two limits, both from reading text rather than the running profile:

* Class names match exactly. ``devices_allowed`` carries no base classes, so a
  device of a subclass (``HEXKinetixDetector``) is not offered for its parent.
* The source is the LOCAL checkout, which can differ from what the server runs.
  Fields typed this way say so in their label.
"""

import ast
from collections.abc import Mapping
from typing import Protocol

from planrunner.protocols import JSON
from planrunner.sources import SourceFinder


class SourceAnnotations(Protocol):
    def for_plan(self, plan: JSON) -> Mapping[str, str]:
        """Parameter name -> its annotation as written in the source, if found."""
        ...


class LocalSourceAnnotations:
    """Annotations from the source ``finder`` locates, read fresh each time (a plan is
    described when it is picked, and an edited checkout should show at once)."""

    def __init__(self, finder: SourceFinder) -> None:
        self._finder = finder

    def for_plan(self, plan: JSON) -> Mapping[str, str]:
        found = self._finder.find(plan["name"], plan.get("module"))
        return annotations_in(found.text) if found else {}


def annotations_in(source: str) -> dict[str, str]:
    """The annotations of the first function defined in ``source``, as text."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    function = next((n for n in tree.body
                     if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)), None)
    if function is None:
        return {}
    a = function.args
    params = [*a.posonlyargs, *a.args, *a.kwonlyargs,
              *(p for p in (a.vararg, a.kwarg) if p is not None)]
    return {p.arg: ast.unparse(p.annotation) for p in params if p.annotation is not None}
