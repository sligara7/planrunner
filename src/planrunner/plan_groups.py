"""Group the server's plans by where they come from, so beamline plans are not buried.

``plans_allowed`` reports each plan's ``module``: ``__main__`` for plans the
profile's startup files define, ``hextools.…`` for hextools, ``bluesky.…`` for
Bluesky's own plans.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from planrunner.protocols import JSON

BEAMLINE = "Beamline profile"
HEXTOOLS = "hextools"
BLUESKY = "Bluesky"
OTHER = "Other"

_ORDER = (BEAMLINE, HEXTOOLS, BLUESKY, OTHER)


@dataclass(frozen=True, slots=True)
class PlanGroup:
    title: str
    names: tuple[str, ...]


def source_of(plan: JSON) -> str:
    """The group a plan belongs to, from its reported module."""
    module = plan.get("module") or "__main__"
    top = module.split(".")[0]
    match top:
        case "__main__" | "":
            return BEAMLINE
        case "hextools":
            return HEXTOOLS
        case "bluesky" | "bluesky_queueserver":
            return BLUESKY
        case _:
            return OTHER


def group_plans(plans: Mapping[str, JSON], filter_text: str = "") -> list[PlanGroup]:
    """Plans whose name contains ``filter_text``, grouped, groups in a fixed order."""
    text = filter_text.strip().lower()
    groups: dict[str, list[str]] = {title: [] for title in _ORDER}
    for name, plan in plans.items():
        if text in name.lower():
            groups[source_of(plan)].append(name)
    return [PlanGroup(title, tuple(sorted(names))) for title, names in groups.items() if names]
