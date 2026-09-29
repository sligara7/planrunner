"""Connecting to the server, and opening/closing the RE worker environment."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from planrunner.client import ConnectionSettings
from planrunner.controllers.commands import Commands
from planrunner.credentials import FoundKey
from planrunner.events import (
    Connected,
    Disconnected,
    Notice,
    PermissionsKnown,
    ServerReachable,
    ServerUnreachable,
    StatusUpdated,
)
from planrunner.permissions import Permissions
from planrunner.protocols import (
    JSON,
    CallRunner,
    ConfigStore,
    Dialogs,
    DoneCallback,
    EventBusLike,
    Feed,
    Outcome,
    QueueServerAPI,
)
from planrunner.status_text import controls_for


@dataclass(frozen=True, slots=True)
class ConnectionForm:
    uri: str
    api_key: str = ""


class ConnectionHandlers(Protocol):
    def on_connect(self) -> None: ...

    def on_disconnect(self) -> None: ...

    def on_open_environment(self) -> None: ...

    def on_close_environment(self) -> None: ...


class ConnectionView(Protocol):
    def set_handlers(self, handlers: ConnectionHandlers) -> None: ...

    def read_form(self) -> ConnectionForm: ...

    def fill_form(self, form: ConnectionForm) -> None: ...

    def show_connection(self, state: str) -> None:
        """``state`` is one of 'disconnected', 'connecting', 'connected', 'unreachable'."""
        ...

    def enable_environment_buttons(self, can_open: bool, can_close: bool) -> None: ...

    def show_access(self, text: str) -> None:
        """What the connection may do, e.g. 'full control' or 'read only'; '' to clear."""
        ...


class KeyLookup(Protocol):
    def find(self, server_uri: str, typed: str = "") -> FoundKey | None: ...


class Connector(CallRunner, Protocol):
    """Opens and closes the connection, and runs calls on it."""

    def connect(
        self, settings: ConnectionSettings, on_done: DoneCallback[QueueServerAPI]
    ) -> None: ...

    def disconnect(self, on_done: DoneCallback[None] | None = None) -> None: ...


class ConnectionController:
    def __init__(
        self,
        *,
        view: ConnectionView,
        connector: Connector,
        commands: Commands,
        feeds: Sequence[Feed],
        bus: EventBusLike,
        dialogs: Dialogs,
        config: ConfigStore,
        keys: KeyLookup,
    ) -> None:
        self._view = view
        self._connector = connector
        self._commands = commands
        self._feeds = feeds
        self._bus = bus
        self._dialogs = dialogs
        self._config = config
        self._keys = keys
        self._uri: str | None = None
        self._allowed = Permissions.full()
        self._status: JSON | None = None

        view.set_handlers(self)
        view.fill_form(ConnectionForm(uri=str(config.load().get("server_uri", ""))))
        view.show_connection("disconnected")
        view.enable_environment_buttons(can_open=False, can_close=False)
        bus.subscribe(StatusUpdated, self._on_status)
        bus.subscribe(ServerUnreachable, lambda _: view.show_connection("unreachable"))
        bus.subscribe(ServerReachable, lambda _: self._on_reachable())

    # --- Handlers ---------------------------------------------------------------

    def on_connect(self) -> None:
        form = self._view.read_form()
        if not form.uri.strip():
            self._dialogs.error("Connect", "Enter the server address, e.g. http://localhost:60610")
            return
        self._stop_feeds()
        uri = form.uri.strip()
        key = self._keys.find(uri, typed=form.api_key)
        settings = ConnectionSettings(uri=uri, api_key=key.key if key else None)
        self._view.show_connection("connecting")
        self._view.show_access("")
        self._connector.connect(
            settings, lambda outcome: self._on_connected(settings, key, outcome)
        )

    def on_disconnect(self) -> None:
        self._stop_feeds()
        self._connector.disconnect()
        self._view.show_connection("disconnected")
        self._view.enable_environment_buttons(can_open=False, can_close=False)
        self._view.show_access("")
        self._status, self._allowed = None, Permissions.full()
        if self._uri is not None:
            self._bus.publish(Disconnected(self._uri))
            self._bus.publish(Notice(f"Disconnected from {self._uri}"))
        self._uri = None

    def on_open_environment(self) -> None:
        self._commands.send("Open environment", lambda api: api.environment_open())

    def on_close_environment(self) -> None:
        if self._dialogs.confirm(
            "Close environment",
            "Close the RE worker environment? Plans cannot run until it is opened again.",
        ):
            self._commands.send("Close environment", lambda api: api.environment_close())

    # --- Events -----------------------------------------------------------------

    def _on_connected(
        self, settings: ConnectionSettings, key: FoundKey | None,
        outcome: Outcome[QueueServerAPI],
    ) -> None:
        if not outcome.ok:
            self._view.show_connection("disconnected")
            self._dialogs.error("Connect", f"Could not connect to {settings.uri}:\n{outcome.error}")
            return
        api = outcome.value
        assert api is not None
        self._uri = settings.uri
        self._config.save({"server_uri": settings.uri})
        self._view.show_connection("connected")
        for feed in self._feeds:
            feed.start(api)
        self._bus.publish(Connected(settings.uri, api))
        using = f" using the API key from {key.origin}" if key else " without an API key"
        self._bus.publish(Notice(f"Connected to {settings.uri}{using}"))
        self._check_permissions()

    def _check_permissions(self) -> None:
        def done(outcome: Outcome[JSON]) -> None:
            if outcome.ok and outcome.value is not None:
                self._set_permissions(Permissions.from_scopes(outcome.value.get("scopes", ())))
            else:  # the server cannot say; let it judge each command
                self._set_permissions(Permissions.full(), note="permissions unknown")

        self._connector.run(lambda api: api.api_scopes(), done)

    def _set_permissions(self, allowed: Permissions, note: str = "") -> None:
        self._allowed = allowed
        self._refresh_environment_buttons()
        text = "read only" if allowed.read_only else note or "full control"
        self._view.show_access(text)
        self._bus.publish(PermissionsKnown(allowed))
        if allowed.read_only:
            self._bus.publish(Notice(
                "Read only: this connection may watch but not change the queue or RunEngine. "
                "Connect with the beamline API key for control."
            ))

    def _on_reachable(self) -> None:
        if self._uri is not None:
            self._view.show_connection("connected")

    def _on_status(self, event: StatusUpdated) -> None:
        self._status = event.status
        self._refresh_environment_buttons()

    def _refresh_environment_buttons(self) -> None:
        controls = controls_for(self._status, self._allowed)
        self._view.enable_environment_buttons(
            can_open=controls.open_environment, can_close=controls.close_environment
        )

    def _stop_feeds(self) -> None:
        for feed in self._feeds:
            feed.stop()
