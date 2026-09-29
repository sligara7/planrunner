"""Sending commands to the server and reporting how they went."""

from collections.abc import Callable

from planrunner.events import Notice
from planrunner.protocols import ApiCall, CallRunner, EventPublisher, Outcome


class Commands:
    """Runs a server call and reports failure (and optionally success) as a ``Notice``.

    Controllers compose one of these rather than each handling errors their own way.
    """

    def __init__(self, runner: CallRunner, bus: EventPublisher) -> None:
        self._runner = runner
        self._bus = bus

    def send[T](
        self,
        what: str,
        call: ApiCall[T],
        on_success: Callable[[T], None] | None = None,
        *,
        announce: bool = True,
    ) -> None:
        """Run ``call``; ``what`` names it in messages, e.g. ``"Start queue"``."""

        def done(outcome: Outcome[T]) -> None:
            if not outcome.ok:
                self._bus.publish(Notice(f"{what} failed: {outcome.error}", is_error=True))
                return
            if announce:
                self._bus.publish(Notice(f"{what}: done"))
            if on_success is not None:
                on_success(outcome.value)  # type: ignore[arg-type]

        self._runner.run(call, done)
