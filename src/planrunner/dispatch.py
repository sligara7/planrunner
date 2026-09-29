"""Dispatchers: how work produced on background threads reaches the UI thread.

``QueueDispatcher`` buffers callbacks until the UI loop drains it (see
``planrunner.ui.pump``). ``ImmediateDispatcher`` runs them inline and exists for
tests and headless use.
"""

import logging
import queue
from collections.abc import Callable

logger = logging.getLogger(__name__)


class QueueDispatcher:
    """Thread-safe FIFO of callbacks, drained on the UI thread."""

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()

    def post(self, callback: Callable[[], None]) -> None:
        self._queue.put(callback)

    def drain(self, max_items: int = 500) -> int:
        """Run up to ``max_items`` pending callbacks; return how many ran.

        A failing callback is logged and does not stop the others: one bad
        handler must not freeze the whole UI.
        """
        ran = 0
        while ran < max_items:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                logger.exception("UI callback failed")
            ran += 1
        return ran


class ImmediateDispatcher:
    """Runs callbacks synchronously on the calling thread."""

    def post(self, callback: Callable[[], None]) -> None:
        callback()
