"""The composition root: the one place that builds every object and wires them.

Everything else receives its collaborators through its constructor, so this
file is also the map of how the application fits together.
"""

import signal
from dataclasses import dataclass
from pathlib import Path

from planrunner.client import ApiFactory, ServerClient, make_http_api
from planrunner.config import JsonConfigStore
from planrunner.controllers.commands import Commands
from planrunner.controllers.connection import ConnectionController, ConnectionForm
from planrunner.controllers.console import ConsoleController
from planrunner.controllers.plans import PlansController
from planrunner.controllers.queue import QueueController
from planrunner.controllers.status import StatusController
from planrunner.credentials import KeyFinder, default_key_finder
from planrunner.dispatch import QueueDispatcher
from planrunner.events import EventBus
from planrunner.feeds import ConsoleFeed, PollingStatusFeed
from planrunner.protocols import Feed
from planrunner.ui.main_window import MainWindow
from planrunner.ui.services import TkDialogs, TkPump


@dataclass(frozen=True, slots=True, kw_only=True)
class AppOptions:
    server_uri: str | None = None
    """Overrides the last-used server address."""
    api_key: str | None = None
    connect: bool = False
    """Connect as soon as the window opens."""
    config_path: Path | None = None
    status_period: float = 1.0


class App:
    def __init__(
        self,
        options: AppOptions,
        api_factory: ApiFactory = make_http_api,
        keys: KeyFinder | None = None,
    ) -> None:
        dispatcher = QueueDispatcher()
        bus = EventBus(dispatcher)
        config = JsonConfigStore(options.config_path)
        self.client = ServerClient(dispatcher, api_factory)
        self.feeds: list[Feed] = [PollingStatusFeed(bus, options.status_period), ConsoleFeed(bus)]
        commands = Commands(self.client, bus)

        self.window = window = MainWindow()
        dialogs = TkDialogs(window.root)
        self.pump = TkPump(window.root, dispatcher)

        # Console first, so notices published while the others start are shown.
        self.console = ConsoleController(
            view=window.console, status_line=window.status_bar, bus=bus, dialogs=dialogs,
            config=config,
        )
        self.status = StatusController(view=window.status_strip, bus=bus)
        self.connection = ConnectionController(
            view=window.connection_bar, connector=self.client, commands=commands,
            feeds=self.feeds, bus=bus, dialogs=dialogs, config=config,
            keys=keys or default_key_finder(),
        )
        self.plans = PlansController(
            plan_list=window.plan_list, form=window.plan_form, commands=commands, bus=bus,
            publisher=bus, dialogs=dialogs,
        )
        self.queue = QueueController(
            view=window.scheduler, commands=commands, bus=bus, publisher=bus, dialogs=dialogs,
        )

        if options.server_uri or options.api_key:
            current = window.connection_bar.read_form()
            window.connection_bar.fill_form(ConnectionForm(
                uri=options.server_uri or current.uri, api_key=options.api_key or current.api_key,
            ))
        self._connect_on_start = options.connect
        window.on_close(self.close)

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self.close())
        self.pump.start()
        if self._connect_on_start:
            self.window.root.after_idle(self.connection.on_connect)
        self.window.root.mainloop()

    def close(self) -> None:
        """Leave the server untouched: stop listening, close the connection, exit."""
        for feed in self.feeds:
            feed.stop()
        self.client.shutdown()
        self.pump.stop()
        self.window.root.destroy()
