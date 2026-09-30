"""Drive the real Qt application against a fake server, end to end (offscreen)."""

import os
import time

import pytest
from fakes import FakeQueueServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from planrunner.app import App, AppOptions
from planrunner.credentials import KeyFinder


def kw(name, **extra):
    return {"name": name, "kind": {"name": "POSITIONAL_OR_KEYWORD"}, **extra}


PLANS = {
    "count": {
        "name": "count", "module": "bluesky.plans",
        "description": "Take one or more readings from detectors.",
        "parameters": [
            kw("detectors", annotation={"type": "list[__READABLE__]"}),
            kw("num", annotation={"type": "int"}, default="1", min="1"),
        ],
    },
    "tomo_flyscan": {
        "name": "tomo_flyscan", "module": "__main__",
        "parameters": [kw("exposure_time", annotation={"type": "float"})],
    },
    "sleep_for_secs": {
        "name": "sleep_for_secs", "module": "__main__",
        "parameters": [kw("secs", annotation={"type": "float"})],
    },
}
DEVICES = {"det1": {"is_readable": True}, "motor": {"is_readable": True, "is_movable": True}}
STATUS = {
    "manager_state": "idle", "worker_environment_exists": True, "items_in_queue": 1,
    "items_in_history": 1, "re_state": "idle", "plan_queue_uid": "q1",
    "plan_history_uid": "h1", "plans_allowed_uid": "p1", "devices_allowed_uid": "d1",
}
PENDING = {"item_type": "plan", "name": "count", "kwargs": {"detectors": ["det1"]},
           "item_uid": "pending-1"}
FINISHED = {"item_type": "plan", "name": "count", "item_uid": "done-1",
            "result": {"exit_status": "completed", "time_start": 1.0, "time_stop": 3.0}}


@pytest.fixture
def app(tmp_path):
    server = FakeQueueServer(
        status_reply=dict(STATUS), plans=dict(PLANS), devices=DEVICES,
        queue_reply={"running_item": {}, "items": [PENDING]},
        history_reply={"items": [FINISHED]},
    )
    application = App(
        AppOptions(server_uri="http://sim:60610", config_path=tmp_path / "config.json",
                   status_period=0.05),
        api_factory=lambda settings: server,
        keys=KeyFinder([]),  # hermetic: ignore this machine's /etc/qs_client and env
    )
    application.server = server  # type: ignore[attr-defined]
    application.dialogs_said_yes = []  # type: ignore[attr-defined]
    yield application
    application.shutdown()


def settle(until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def connect(app):
    app.connection.on_connect()
    settle(lambda: "count" in app.window.plan_list.names())


def always_yes(app):
    for controller in (app.plans, app.queue, app.connection):
        controller._dialogs.confirm = lambda *_: True


def test_plans_grouped_beamline_first_and_form_follows_selection(app):
    connect(app)
    assert app.window.plan_list.names() == ["sleep_for_secs", "tomo_flyscan", "count"]
    app.plans.on_plan_selected("count")
    assert app.window.plan_form.current_plan() == "count"
    assert set(app.window.plan_form.read_values()) == {"detectors", "num"}


def test_form_clears_when_its_plan_disappears(app):
    """The bug AJ saw: the form kept a plan the server no longer offered."""
    connect(app)
    app.plans.on_plan_selected("count")
    app.server.plans = {k: v for k, v in PLANS.items() if k != "count"}
    app.plans._catalog.reload()
    settle(lambda: app.window.plan_form.current_plan() == "")
    assert "count" not in app.window.plan_list.names()


def test_add_to_schedule_with_iterations_reveals_scheduler(app):
    connect(app)
    assert not app.window.scheduler_visible
    app.plans.on_plan_selected("count")
    grid = app.window.plan_form.grid
    grid.field("detectors").set(["det1"])
    grid.field("num").set("3")
    app.window.plan_form._iterations.setValue(2)
    app.plans.on_add_to_schedule()
    settle(lambda: app.server.called("item_add_batch"))
    (items,), kwargs = app.server.called("item_add_batch")[0]
    assert items == [{"item_type": "plan", "name": "count",
                      "kwargs": {"detectors": ["det1"], "num": 3}}] * 2
    assert kwargs == {"pos": "back"}
    settle(lambda: app.window.scheduler_visible)


def test_schedule_table_shows_finished_and_pending_with_status(app):
    connect(app)
    scheduler = app.window.scheduler
    settle(lambda: scheduler.row_count() == 2)
    assert [scheduler.cell(r, 3) for r in range(2)] == ["Done", "Pending"]
    assert scheduler.cell(1, 2).startswith("count")


def test_task_details_edit_and_save_updates_the_item(app):
    connect(app)
    scheduler = app.window.scheduler
    settle(lambda: scheduler.row_count() == 2)
    scheduler.select_row(1)
    settle(lambda: scheduler._task_title.text() == "count")
    app.queue.on_edit_task()
    scheduler._task_grid.field("num").set("7")
    app.queue.on_save_task()
    settle(lambda: app.server.called("item_update"))
    (updated,), _ = app.server.called("item_update")[0]
    assert updated["item_uid"] == "pending-1"
    assert updated["kwargs"] == {"detectors": ["det1"], "num": 7}


def test_run_queue_with_iterations_copies_the_queue_then_starts(app):
    connect(app)
    settle(lambda: app.window.scheduler.row_count() == 2)
    app.queue.on_run_queue(3)
    settle(lambda: app.server.called("queue_start"))
    (copies,), _ = app.server.called("item_add_batch")[0]
    assert copies == [{"item_type": "plan", "name": "count",
                       "kwargs": {"detectors": ["det1"]}}] * 2


def test_add_sleep_queues_the_beamline_sleep_plan(app):
    connect(app)
    app.queue.on_add_sleep(2.5, position=1)
    settle(lambda: app.server.called("item_add_batch"))
    (items,), kwargs = app.server.called("item_add_batch")[0]
    assert items == [{"item_type": "plan", "name": "sleep_for_secs", "kwargs": {"secs": 2.5}}]
    assert kwargs == {"pos": 0}


def test_read_only_connection_greys_out_every_write_control(app):
    app.server.scopes = ["read:status", "read:console"]  # anonymous, as bsqs configures it
    app.connection.on_connect()
    settle(lambda: "read only" in app.window.server_bar._access.text())
    settle(lambda: app.server.called("status"))
    QApplication.processEvents()
    scheduler, form = app.window.scheduler, app.window.plan_form
    buttons = [scheduler._run_queue, scheduler._pause, scheduler._resume, scheduler._stop,
               scheduler._clear, scheduler._add_sleep, form._add, form._run_now,
               app.window.environment_bar._open, app.window.environment_bar._close]
    assert [b.text() for b in buttons if b.isEnabled()] == []
    assert app.window.plan_list.names() == []
    assert not app.server.called("plans_allowed")


def test_closing_the_gui_sends_nothing_to_the_server(app):
    connect(app)
    writes = {"queue_start", "queue_stop", "queue_clear", "re_pause", "re_abort", "re_halt",
              "item_add_batch", "item_remove", "item_update", "environment_close"}
    app.shutdown()
    assert not writes & {name for name, _, _ in app.server.calls}
