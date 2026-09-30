"""Stopping the running plan, ScriptRunner-style: one click, whatever state it is in.

The RunEngine only accepts ``stop`` while paused, so "Stop run" pauses immediately
first and sends ``stop`` once the manager reports it is paused. The plan ends
cleanly (its run is closed as successful).
"""

from planrunner.controllers.commands import Commands
from planrunner.events import Disconnected, StatusUpdated
from planrunner.protocols import JSON, EventSubscriber


class RunControl:
    def __init__(self, *, commands: Commands, bus: EventSubscriber) -> None:
        self._commands = commands
        self._status: JSON = {}
        self._stop_when_paused = False
        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(Disconnected, lambda _: self._forget())

    @property
    def running(self) -> bool:
        return self._status.get("manager_state") in ("executing_queue", "executing_task")

    @property
    def paused(self) -> bool:
        return self._status.get("manager_state") == "paused"

    def stop_run(self) -> None:
        if self.paused:
            self._commands.send("Stop run", lambda api: api.re_stop())
        elif self.running:
            self._stop_when_paused = True
            self._commands.send("Pause to stop", lambda api: api.re_pause("immediate"),
                                announce=False)

    def _on_status(self, event: StatusUpdated) -> None:
        self._status = event.status
        if self._stop_when_paused and self.paused:
            self._stop_when_paused = False
            self._commands.send("Stop run", lambda api: api.re_stop())
        elif self._stop_when_paused and not self.running:
            self._stop_when_paused = False  # it finished on its own first

    def _forget(self) -> None:
        self._status, self._stop_when_paused = {}, False
