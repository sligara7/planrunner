"""What the connected user may do, from the httpserver's scopes (``/api/auth/scopes``).

The HEX httpserver lets anyone read (status, queue, history, console) and gives
full control only to callers presenting the API key. Knowing the scopes up front
lets the GUI grey out what would be refused, instead of letting clicks fail.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class Permissions:
    edit_queue: bool = True
    """Add, edit, move, duplicate and delete queue items (``write:queue:edit``)."""
    control_queue: bool = True
    """Start/stop the queue, loop mode (``write:queue:control``)."""
    control_plan: bool = True
    """Pause, resume, stop, abort, halt the running plan (``write:plan:control``)."""
    control_manager: bool = True
    """Open/close the RE worker environment (``write:manager:control``)."""
    execute: bool = True
    """Run an item immediately without queueing it (``write:execute``)."""
    read_queue: bool = True
    """See the queue (``read:queue``)."""
    read_history: bool = True
    """See the run history (``read:history``)."""
    read_resources: bool = True
    """See the allowed plans and devices (``read:resources``)."""

    @classmethod
    def full(cls) -> Self:
        """Used when the server cannot say: let it be the judge of each command."""
        return cls()

    @classmethod
    def none(cls) -> Self:
        return cls(*([False] * 8))

    @classmethod
    def from_scopes(cls, scopes: Iterable[str]) -> Self:
        granted = set(scopes)
        return cls(
            edit_queue="write:queue:edit" in granted,
            control_queue="write:queue:control" in granted,
            control_plan="write:plan:control" in granted,
            control_manager="write:manager:control" in granted,
            execute="write:execute" in granted,
            read_queue="read:queue" in granted,
            read_history="read:history" in granted,
            read_resources="read:resources" in granted,
        )

    @property
    def read_only(self) -> bool:
        return not any(
            (self.edit_queue, self.control_queue, self.control_plan, self.control_manager,
             self.execute)
        )
