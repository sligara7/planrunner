"""The server client: runs queueserver calls on one worker thread.

The Tk thread must never block on the network, so every call goes through
``ServerClient.run``: the call executes on the worker thread and its
``Outcome`` is handed back through the injected ``Dispatcher`` (the UI thread).
Calls run strictly in submission order.
"""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from planrunner.protocols import ApiCall, Dispatcher, DoneCallback, Outcome, QueueServerAPI

logger = logging.getLogger(__name__)


class NotConnectedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Not connected to a server")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectionSettings:
    """How to reach and authenticate with bluesky-httpserver.

    Give either ``api_key`` or ``username`` + ``password`` (or neither, for a
    server with anonymous access). Never pass a username without a password:
    the underlying client would prompt on the terminal.
    """

    uri: str
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    auth_provider: str | None = None
    timeout: float = 5.0


type ApiFactory = Callable[[ConnectionSettings], QueueServerAPI]


def make_http_api(settings: ConnectionSettings) -> QueueServerAPI:
    """Build and authenticate a ``bluesky_queueserver_api.http.REManagerAPI``."""
    from bluesky_queueserver_api.http import REManagerAPI  # noqa: PLC0415 - heavy import

    api = REManagerAPI(
        http_server_uri=settings.uri,
        http_auth_provider=settings.auth_provider,
        timeout=settings.timeout,
        console_monitor_poll_period=0.5,
    )
    if settings.api_key:
        api.set_authorization_key(api_key=settings.api_key)
    elif settings.username:
        if not settings.password:
            raise ValueError("A password is required to log in")
        api.login(settings.username, password=settings.password, provider=settings.auth_provider)
    return api


class ServerClient:
    """Owns the connection and executes calls on a single worker thread.

    Implements ``planrunner.protocols.CallRunner``.
    """

    def __init__(self, dispatcher: Dispatcher, api_factory: ApiFactory = make_http_api) -> None:
        self._dispatcher = dispatcher
        self._api_factory = api_factory
        self._api: QueueServerAPI | None = None  # touched only on the worker thread
        self._jobs: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._worker = threading.Thread(target=self._work, name="planrunner-client", daemon=True)
        self._worker.start()

    # --- Public API (call from the UI thread) ---------------------------------

    def connect(
        self, settings: ConnectionSettings, on_done: DoneCallback[QueueServerAPI]
    ) -> None:
        """Replace any current connection with a new one, checked with ``status()``."""

        def job() -> QueueServerAPI:
            self._close_api()
            api = self._api_factory(settings)
            try:
                api.status(reload=True)
            except Exception:
                api.close()
                raise
            self._api = api
            return api

        self._submit(job, on_done)

    def disconnect(self, on_done: DoneCallback[None] | None = None) -> None:
        self._submit(self._close_api, on_done)

    def run[T](self, call: ApiCall[T], on_done: DoneCallback[T] | None = None) -> None:
        def job() -> T:
            if self._api is None:
                raise NotConnectedError()
            return call(self._api)

        self._submit(job, on_done)

    def shutdown(self) -> None:
        """Close the connection and stop the worker. Never touches the queue or RunEngine."""
        self._jobs.put(self._close_api)
        self._jobs.put(None)
        self._worker.join(timeout=2)

    # --- Worker ---------------------------------------------------------------

    def _submit[T](self, job: Callable[[], T], on_done: DoneCallback[T] | None) -> None:
        def wrapped() -> None:
            try:
                outcome: Outcome[T] = Outcome(value=job())
            except Exception as ex:
                logger.debug("Server call failed", exc_info=True)
                outcome = Outcome(error=ex)
            if (callback := on_done) is not None:
                self._dispatcher.post(lambda: callback(outcome))

        self._jobs.put(wrapped)

    def _work(self) -> None:
        while (job := self._jobs.get()) is not None:
            job()

    def _close_api(self) -> None:
        api, self._api = self._api, None
        if api is not None:
            try:
                api.close()
            except Exception:
                logger.debug("Error closing API client", exc_info=True)
