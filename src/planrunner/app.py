"""The composition root: the one place that builds every object and wires them.

Everything else receives its collaborators through its constructor, so this
file is also the map of how the application fits together.
"""

import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from planrunner.client import ApiFactory, ServerClient, make_http_api
from planrunner.config import JsonConfigStore
from planrunner.controllers.catalog import CatalogStore
from planrunner.controllers.commands import Commands
from planrunner.controllers.connection import ConnectionController, ConnectionForm
from planrunner.controllers.console import ConsoleController
from planrunner.controllers.plans import PlansController
from planrunner.controllers.queue import QueueController
from planrunner.controllers.run_control import RunControl
from planrunner.controllers.source import SourceController
from planrunner.controllers.status import StatusController
from planrunner.credentials import KeyFinder, default_key_finder
from planrunner.dispatch import QueueDispatcher
from planrunner.events import EventBus
from planrunner.feeds import ConsoleFeed, PollingStatusFeed
from planrunner.protocols import Feed
from planrunner.source_types import LocalSourceAnnotations
from planrunner.sources import SourceFinder
from planrunner.ui.main_window import MainWindow
from planrunner.ui.services import QtDialogs, QtPump
from planrunner.ui.style import apply_style


@dataclass(frozen=True, slots=True, kw_only=True)
class AppOptions:
    server_uri: str | None = None
    """Overrides the last-used server address."""
    api_key: str | None = None
    connect: bool = False
    """Connect as soon as the window opens."""
    source_roots: Sequence[Path] = field(default_factory=tuple)
    """Local checkouts (profile collection, hextools) the plan source viewer reads."""
    config_path: Path | None = None
    status_period: float = 1.0


class App:
    def __init__(
        self,
        options: AppOptions,
        api_factory: ApiFactory = make_http_api,
        keys: KeyFinder | None = None,
    ) -> None:
        self.qt = QApplication.instance() or QApplication(sys.argv[:1])
        apply_style(self.qt)  # type: ignore[arg-type]

        dispatcher = QueueDispatcher()
        bus = EventBus(dispatcher)
        config = JsonConfigStore(options.config_path)
        self.client = ServerClient(dispatcher, api_factory)
        self.feeds: list[Feed] = [PollingStatusFeed(bus, options.status_period), ConsoleFeed(bus)]
        commands = Commands(self.client, bus)
        finder = SourceFinder(options.source_roots)
        catalog = CatalogStore(commands=commands, bus=bus,
                               source_types=LocalSourceAnnotations(finder))
        run_control = RunControl(commands=commands, bus=bus)

        self.window = window = MainWindow()
        dialogs = QtDialogs(window.window)
        self.pump = QtPump(dispatcher)

        # Console first, so notices published while the others start are shown.
        self.console = ConsoleController(
            view=window.console, status_line=window.status_bar, bus=bus, dialogs=dialogs,
            config=config,
        )
        self.status = StatusController(view=window.environment_bar, bus=bus)
        self.connection = ConnectionController(
            view=window.top_bars, connector=self.client, commands=commands,
            feeds=self.feeds, bus=bus, dialogs=dialogs, config=config,
            keys=keys or default_key_finder(),
        )
        self.plans = PlansController(
            plan_list=window.plan_list, form=window.plan_form, catalog=catalog,
            commands=commands, run_control=run_control, bus=bus, dialogs=dialogs,
        )
        self.queue = QueueController(
            view=window.scheduler, catalog=catalog, commands=commands,
            run_control=run_control, bus=bus, dialogs=dialogs,
        )
        self.source = SourceController(
            view=window.source_viewer, finder=finder,
            catalog=catalog, bus=bus, dialogs=dialogs,
        )

        if options.server_uri or options.api_key:
            current = window.server_bar.read_form()
            window.server_bar.fill_form(ConnectionForm(
                uri=options.server_uri or current.uri, api_key=options.api_key or current.api_key,
            ))
        self._connect_on_start = options.connect
        window.on_close(self.shutdown)
        self.pump.start()

    def run(self) -> int:
        # Let Ctrl-C in the terminal close the window (Qt otherwise swallows it).
        signal.signal(signal.SIGINT, lambda *_: self.window.window.close())
        keepalive = QTimer()
        keepalive.start(250)
        keepalive.timeout.connect(lambda: None)
        self.window.show()
        if self._connect_on_start:
            QTimer.singleShot(0, self.connection.on_connect)
        return self.qt.exec()

    def shutdown(self) -> None:
        """Leave the server untouched: stop listening, close the connection."""
        for feed in self.feeds:
            feed.stop()
        self.client.shutdown()
        self.pump.stop()
