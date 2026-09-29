"""Feeds: background threads that turn server state into events.

Both feeds are strictly read-only: they never call anything that changes the
queue or the RunEngine, so a GUI crash or disconnect cannot disturb a scan.

``PollingStatusFeed`` polls ``status()`` and re-fetches the queue and history
only when their uids change. ``ConsoleFeed`` streams the RE worker's console.
A websocket implementation (httpserver >= 0.0.14) can replace either one; both
satisfy ``planrunner.protocols.Feed``.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from planrunner.events import (
    AllowedChanged,
    ConsoleText,
    HistoryUpdated,
    QueueUpdated,
    ServerReachable,
    ServerUnreachable,
    StatusUpdated,
)
from planrunner.protocols import EventPublisher, QueueServerAPI

logger = logging.getLogger(__name__)


class _BackgroundLoop:
    """Runs ``step(api)`` repeatedly on a daemon thread until stopped.

    A helper the feeds compose (not a base class).
    """

    def __init__(self, name: str, step: Callable[[QueueServerAPI], None], period: float) -> None:
        self._name = name
        self._step = step
        self._period = period
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, api: QueueServerAPI) -> None:
        self.stop()
        self._stop = stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                self._step(api)
                stop.wait(self._period)

        self._thread = threading.Thread(target=loop, name=self._name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None


@dataclass(slots=True)
class _SeenUids:
    """The uids the feed last reported, so it only fetches what changed."""

    queue: str | None = None
    history: str | None = None
    plans_allowed: str | None = None
    devices_allowed: str | None = None
    reachable: bool | None = None


class PollingStatusFeed:
    """Publishes status every poll, and queue/history/allowed changes when they occur."""

    def __init__(self, bus: EventPublisher, period: float = 1.0) -> None:
        self._bus = bus
        self._seen = _SeenUids()
        self._loop = _BackgroundLoop("planrunner-status", self.poll_once, period)

    def start(self, api: QueueServerAPI) -> None:
        self._seen = _SeenUids()
        self._loop.start(api)

    def stop(self) -> None:
        self._loop.stop()

    def poll_once(self, api: QueueServerAPI) -> None:
        """One poll. Public so tests can drive the feed without a thread."""
        try:
            status = api.status(reload=True)
            self._publish_changes(api, status)
        except Exception as ex:
            if self._seen.reachable is not False:
                self._bus.publish(ServerUnreachable(error=str(ex)))
            self._seen.reachable = False
            return
        if self._seen.reachable is not True:
            self._bus.publish(ServerReachable())
        self._seen.reachable = True

    def _publish_changes(self, api: QueueServerAPI, status: dict) -> None:
        self._bus.publish(StatusUpdated(status))
        seen = self._seen

        if (uid := status.get("plan_queue_uid")) != seen.queue:
            reply = api.queue_get(reload=True)
            self._bus.publish(
                QueueUpdated(running_item=reply.get("running_item") or None,
                             items=tuple(reply.get("items", ())))
            )
            seen.queue = uid

        if (uid := status.get("plan_history_uid")) != seen.history:
            reply = api.history_get(reload=True)
            self._bus.publish(HistoryUpdated(items=tuple(reply.get("items", ()))))
            seen.history = uid

        plans_uid, devices_uid = status.get("plans_allowed_uid"), status.get("devices_allowed_uid")
        if (plans_uid, devices_uid) != (seen.plans_allowed, seen.devices_allowed):
            # The first poll counts as a change: it is what triggers the first load.
            self._bus.publish(AllowedChanged())
            seen.plans_allowed, seen.devices_allowed = plans_uid, devices_uid


class ConsoleFeed:
    """Streams the RE worker's console output as ``ConsoleText`` events.

    Each pass waits up to ``wait`` seconds for output, drains whatever else is
    buffered, publishes it as one event, then rests for ``period`` seconds.
    """

    def __init__(self, bus: EventPublisher, wait: float = 0.2, period: float = 0.1) -> None:
        self._bus = bus
        self._wait = wait
        self._api: QueueServerAPI | None = None
        self._loop = _BackgroundLoop("planrunner-console", self.read_once, period)

    def start(self, api: QueueServerAPI) -> None:
        self.stop()
        self._api = api
        api.console_monitor.enable()
        self._loop.start(api)

    def stop(self) -> None:
        self._loop.stop()
        if self._api is not None:
            try:
                self._api.console_monitor.disable()
            except Exception:
                logger.debug("Error disabling console monitor", exc_info=True)
            self._api = None

    def read_once(self, api: QueueServerAPI) -> None:
        """Publish everything the console monitor has buffered (one event per pass)."""
        monitor = api.console_monitor
        chunks: list[str] = []
        timeout: float | None = self._wait
        while True:
            try:
                msg = monitor.next_msg(timeout=timeout)
            except Exception:
                break  # nothing (more) buffered
            chunks.append(msg.get("msg", ""))
            timeout = None  # after the first message, only take what is already there
        if text := "".join(chunks):
            self._bus.publish(ConsoleText(text))
