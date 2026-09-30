"""End to end against a real queueserver: the local bsqs replica (sim/queueserver).

Skipped unless PLANRUNNER_LIVE_URI is set; `pixi run live-test` sets it.
PLANRUNNER_LIVE_DETECTOR names a readable device the profile offers ("det1" in the
queueserver's built-in simulated profile; e.g. "theta" in the HEX profile).
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
URI = os.environ.get("PLANRUNNER_LIVE_URI")
KEY = os.environ.get("PLANRUNNER_LIVE_KEY", "")
DETECTOR = os.environ.get("PLANRUNNER_LIVE_DETECTOR", "det1")
pytestmark = pytest.mark.skipif(not URI, reason="set PLANRUNNER_LIVE_URI to run live tests")

from PySide6.QtWidgets import QApplication  # noqa: E402

from planrunner.app import App, AppOptions  # noqa: E402
from planrunner.controllers.connection import ConnectionForm  # noqa: E402
from planrunner.credentials import KeyFinder  # noqa: E402


class AlwaysYes:
    """Answers every confirmation with yes; records errors instead of showing them."""

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
    yield application
    application.shutdown()


def settle(until, timeout=30.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def connect(app, key: str) -> None:
    app.window.server_bar.fill_form(ConnectionForm(uri=URI, api_key=key))
    app.connection.on_connect()
    settle(lambda: app.connection._uri is not None, what="connection")


def status(app) -> dict:
    return app.queue._status or {}


def history(app) -> list:
    return app.queue._finished


def test_anonymous_connection_is_a_read_only_monitor(app):
    connect(app, key="")
    settle(lambda: "read only" in app.window.server_bar._access.text())
    settle(lambda: status(app).get("manager_state"), what="status")
    assert app.window.plan_list.names() == []
    assert "failed" not in app.window.console.text().lower()
    assert not app.window.scheduler._run_queue.isEnabled()


@pytest.mark.skipif(not KEY, reason="set PLANRUNNER_LIVE_KEY for control tests")
def test_schedule_run_pause_stop_with_api_key(app):
    connect(app, key=KEY)
    settle(lambda: "full control" in app.window.server_bar._access.text())
    settle(lambda: "count" in app.window.plan_list.names(), what="plans")

    if not status(app).get("worker_environment_exists"):
        settle(lambda: status(app).get("manager_state") == "idle")
        app.connection.on_open_environment()
        settle(lambda: status(app).get("worker_environment_exists"), timeout=120,
               what="environment open")
        settle(lambda: "count" in app.window.plan_list.names(), what="live plans")
    app.queue.on_clear()
    settle(lambda: status(app).get("items_in_queue") == 0 and not app.queue._pending,
           what="queue cleared")
    finished_before = status(app).get("items_in_history", 0)

    # Build count(<detector>, num=3) in the form and schedule it.
    app.plans.on_plan_selected("count")
    grid = app.window.plan_form.grid
    grid.field("detectors").set([DETECTOR])
    grid.field("num").set("3")
    app.plans.on_add_to_schedule()
    settle(lambda: len(app.queue._pending) == 1, what="item scheduled")
    assert app.queue._pending[0]["kwargs"] == {"detectors": [DETECTOR], "num": 3}
    settle(lambda: app.window.scheduler_visible, what="scheduler revealed")

    settle(app.window.scheduler._run_queue.isEnabled)
    app.queue.on_run_queue(1)
    settle(lambda: status(app).get("items_in_history", 0) == finished_before + 1,
           timeout=60, what="plan finished")
    settle(lambda: history(app) and history(app)[-1]["name"] == "count", what="history shown")
    assert history(app)[-1]["result"]["exit_status"] == "completed"
    settle(lambda: "Done" in [app.window.scheduler.cell(r, 3)
                              for r in range(app.window.scheduler.row_count())])

    # A slow plan: 'Stop run' pauses it now, then stops it cleanly.
    app.plans.on_plan_selected("count")
    grid = app.window.plan_form.grid
    grid.field("detectors").set([DETECTOR])
    grid.field("num").set("30")
    grid.field("delay").set("1")
    app.plans.on_add_to_schedule()
    settle(lambda: len(app.queue._pending) == 1, what="slow item scheduled")
    app.queue.on_run_queue(1)
    settle(lambda: status(app).get("re_state") == "running", what="running")
    time.sleep(1.5)
    app.plans.on_stop_run()
    settle(lambda: status(app).get("items_in_history", 0) == finished_before + 2,
           timeout=60, what="stopped plan in history")
    settle(lambda: len(history(app)) == finished_before + 2 or
           history(app)[-1]["result"]["exit_status"] == "stopped", what="history refreshed")
    assert history(app)[-1]["result"]["exit_status"] == "stopped"

    assert app.dialogs.errors == []


CAPTURE_CAMERA = os.environ.get("PLANRUNNER_LIVE_CAPTURE_CAMERA")


@pytest.mark.skipif(not CAPTURE_CAMERA,
                    reason="set PLANRUNNER_LIVE_CAPTURE_CAMERA (hextools profile on the sim)")
def test_trigger_button_releases_a_waiting_capture(app):
    """hextools' phantom_capture waits for the operator's event trigger; the button sends it."""
    from bluesky_queueserver_api import BPlan  # noqa: PLC0415
    from bluesky_queueserver_api.http import REManagerAPI  # noqa: PLC0415

    connect(app, KEY)
    settle(lambda: "phantom_capture" in app.plans._catalog.plans, what="plans")
    api = REManagerAPI(http_server_uri=URI)
    api.set_authorization_key(api_key=KEY)
    try:
        api.item_execute(BPlan("phantom_capture", camera=CAPTURE_CAMERA, num_images=3,
                               exposure_time=0.01))
        button = app.window.scheduler._trigger
        settle(button.isEnabled, timeout=60, what="the Trigger button")
        assert button.text() == f"Trigger {CAPTURE_CAMERA}"
        time.sleep(2)
        assert status(app).get("manager_state") == "executing_queue"  # still waiting
        button.click()
        settle(lambda: status(app).get("manager_state") == "idle", timeout=60,
               what="the capture to finish")
        last = api.history_get()["items"][-1]
        assert (last["name"], last["result"]["exit_status"]) == ("phantom_capture", "completed")
        assert not button.isEnabled()
    finally:
        api.close()
