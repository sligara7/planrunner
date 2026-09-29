"""End to end against a real queueserver: the local bsqs replica (sim/queueserver).

Skipped unless PLANRUNNER_LIVE_URI is set; `pixi run live-test` sets it. Uses the
queueserver's built-in simulated profile (det1, det2, motor, count, ...).
"""

import os
import time

import pytest

tk = pytest.importorskip("tkinter")
URI = os.environ.get("PLANRUNNER_LIVE_URI")
KEY = os.environ.get("PLANRUNNER_LIVE_KEY", "")
pytestmark = pytest.mark.skipif(not URI, reason="set PLANRUNNER_LIVE_URI to run live tests")

from planrunner.app import App, AppOptions  # noqa: E402
from planrunner.controllers.connection import ConnectionForm  # noqa: E402
from planrunner.credentials import KeyFinder  # noqa: E402


class AlwaysYes:
    """Answers every confirmation dialog with yes; records errors instead of showing them."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def confirm(self, title: str, message: str) -> bool:
        return True

    def error(self, title: str, message: str) -> None:
        self.errors.append(f"{title}: {message}")

    def ask_save_path(self, title: str, initial_file: str) -> str | None:
        return None


@pytest.fixture
def app(tmp_path):
    application = App(
        AppOptions(server_uri=URI, config_path=tmp_path / "config.json", status_period=0.2),
        keys=KeyFinder([]),
    )
    dialogs = AlwaysYes()
    for controller in (application.connection, application.plans, application.queue):
        controller._dialogs = dialogs
    application.dialogs = dialogs  # type: ignore[attr-defined]
    application.window.root.withdraw()
    application.pump.start()
    yield application
    application.close()


def settle(app, until, timeout=30.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.window.root.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def connect(app, key: str) -> None:
    app.window.connection_bar.fill_form(ConnectionForm(uri=URI, api_key=key))
    app.connection.on_connect()
    settle(app, lambda: app.connection._uri is not None, what="connection")


def status(app) -> dict:
    return app.queue._status or {}


def console_text(app) -> str:
    return app.window.console._text.get("1.0", "end")


def test_anonymous_connection_is_a_read_only_monitor(app):
    connect(app, key="")
    settle(app, lambda: "read only" in app.window.connection_bar._access.cget("text"))
    settle(app, lambda: status(app).get("manager_state"), what="status")
    assert app.window.plan_list._names == []
    assert "failed" not in console_text(app).lower()
    assert all(b.instate(["disabled"]) for b in app.window.scheduler._buttons.values())


@pytest.mark.skipif(not KEY, reason="set PLANRUNNER_LIVE_KEY for control tests")
def test_queue_run_pause_abort_with_api_key(app):
    connect(app, key=KEY)
    settle(app, lambda: "full control" in app.window.connection_bar._access.cget("text"))
    settle(app, lambda: "count" in app.window.plan_list._names, what="plans")

    # Start clean: open the environment, empty the queue.
    if not status(app).get("worker_environment_exists"):
        settle(app, lambda: status(app).get("manager_state") == "idle")
        app.connection.on_open_environment()
        settle(app, lambda: status(app).get("worker_environment_exists"), timeout=60,
               what="environment open")
    app.queue.on_clear()
    settle(app, lambda: status(app).get("items_in_queue") == 0, what="queue cleared")
    history_before = status(app).get("items_in_history", 0)

    # Build count(det1, det2, num=3) in the form and queue it.
    app.plans.on_plan_selected("count")
    fields = app.window.plan_form._fields
    fields["detectors"].set(["det1", "det2"])
    fields["num"].set("3")
    app.plans.on_add_to_queue()
    settle(app, lambda: status(app).get("items_in_queue") == 1, what="item queued")
    queued = app.queue._items[0]
    assert queued["name"] == "count"
    assert queued["kwargs"] == {"detectors": ["det1", "det2"], "num": 3}

    # Run it to completion.
    settle(app, lambda: app.window.scheduler._buttons["start"].instate(["!disabled"]))
    app.queue.on_start()
    settle(app, lambda: status(app).get("items_in_history", 0) == history_before + 1,
           timeout=60, what="plan finished")
    settle(app, lambda: app.queue._history, what="history shown")
    assert app.queue._history[-1]["result"]["exit_status"] == "completed"
    settle(app, lambda: "count" in console_text(app), what="console output")

    # A slow plan: pause it mid-run, then abort.
    app.plans.on_plan_selected("count")
    fields = app.window.plan_form._fields
    fields["detectors"].set(["det1"])
    fields["num"].set("30")
    fields["delay"].set("1")
    app.plans.on_add_to_queue()
    settle(app, lambda: status(app).get("items_in_queue") == 1, what="slow item queued")
    app.queue.on_start()
    settle(app, lambda: status(app).get("re_state") == "running", what="running")
    time.sleep(1.5)
    app.queue.on_pause(immediate=True)
    settle(app, lambda: status(app).get("manager_state") == "paused", what="paused")
    assert app.window.scheduler._buttons["abort"].instate(["!disabled"])
    app.queue.on_abort()
    settle(app, lambda: status(app).get("items_in_history", 0) == history_before + 2,
           timeout=60, what="aborted plan in history")
    settle(app, lambda: len(app.queue._history) == history_before + 2)
    assert app.queue._history[-1]["result"]["exit_status"] == "aborted"

    assert app.dialogs.errors == []
