"""Drive the real Tk application against a fake server, end to end."""

import os
import time

import pytest
from fakes import FakeQueueServer

tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and os.name != "nt", reason="needs a display"
)

from planrunner.app import App, AppOptions  # noqa: E402
from planrunner.credentials import KeyFinder  # noqa: E402

PLANS = {
    "count": {
        "name": "count",
        "description": "Take one or more readings from detectors.",
        "parameters": [
            {"name": "detectors", "kind": {"name": "POSITIONAL_OR_KEYWORD"},
             "annotation": {"type": "list[__READABLE__]"}},
            {"name": "num", "kind": {"name": "POSITIONAL_OR_KEYWORD"},
             "annotation": {"type": "int"}, "default": "1", "min": "1"},
        ],
    },
}
DEVICES = {"det1": {"is_readable": True}, "motor": {"is_readable": True, "is_movable": True}}
STATUS = {
    "manager_state": "idle", "worker_environment_exists": True, "items_in_queue": 1,
    "items_in_history": 0, "re_state": "idle", "plan_queue_uid": "q1",
    "plan_history_uid": "h1", "plans_allowed_uid": "p1", "devices_allowed_uid": "d1",
}


@pytest.fixture
def app(tmp_path):
    server = FakeQueueServer(
        status_reply=STATUS, plans=PLANS, devices=DEVICES,
        queue_reply={"running_item": {}, "items": [
            {"item_type": "plan", "name": "count", "kwargs": {"detectors": ["det1"]},
             "item_uid": "u1"},
        ]},
    )
    application = App(
        AppOptions(server_uri="http://sim:60610", config_path=tmp_path / "config.json",
                   status_period=0.05),
        api_factory=lambda settings: server,
        keys=KeyFinder([]),  # hermetic: ignore this machine's /etc/qs_client and env
    )
    application.window.root.withdraw()
    application.server = server  # type: ignore[attr-defined]
    application.pump.start()
    yield application
    application.close()


def settle(app, until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.window.root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def test_connect_load_plans_and_queue_one(app):
    window, server = app.window, app.server
    app.connection.on_connect()
    settle(app, lambda: window.plan_list._names == ["count"])
    settle(app, lambda: len(window.scheduler._queue_tree.get_children()) == 1)

    app.plans.on_plan_selected("count")
    form = window.plan_form
    assert set(form._fields) == {"detectors", "num"}
    form._fields["detectors"].set(["det1"])
    form._fields["num"].set("3")
    app.plans.on_add_to_queue()
    settle(app, lambda: server.called("item_add_batch"))

    (items,), kwargs = server.called("item_add_batch")[0]
    assert items == [{"item_type": "plan", "name": "count",
                      "kwargs": {"detectors": ["det1"], "num": 3}}]
    assert kwargs == {"pos": "back"}


def test_bad_input_is_shown_not_sent(app):
    app.connection.on_connect()
    settle(app, lambda: app.window.plan_list._names == ["count"])
    app.plans.on_plan_selected("count")
    app.window.plan_form._fields["num"].set("0")
    app.plans.on_add_to_queue()
    app.window.root.update()
    label, _ = app.window.plan_form._help["num"]
    assert "must be >= 1" in label.cget("text")
    assert not app.server.called("item_add_batch")


def test_closing_the_gui_sends_nothing_to_the_server(app):
    app.connection.on_connect()
    settle(app, lambda: app.server.called("status"))
    writes = {"queue_start", "queue_stop", "queue_clear", "re_pause", "re_abort", "re_halt",
              "item_add_batch", "item_remove", "environment_close"}
    app.close()
    assert not writes & {name for name, _, _ in app.server.calls}
    app.close = lambda: None  # already closed


def test_read_only_connection_greys_out_every_write_control(app):
    window, server = app.window, app.server
    server.scopes = ["read:status", "read:console"]  # anonymous, as bsqs configures it
    app.connection.on_connect()
    settle(app, lambda: "read only" in window.connection_bar._access.cget("text"))
    settle(app, lambda: server.called("status"))
    app.window.root.update()

    buttons = window.scheduler._buttons
    enabled = [key for key, button in buttons.items() if not button.instate(["disabled"])]
    assert enabled == []
    assert window.plan_form._add.instate(["disabled"])
    assert window.plan_form._run_now.instate(["disabled"])
    assert window.connection_bar._open_env.instate(["disabled"])
    assert window.connection_bar._close_env.instate(["disabled"])
    assert window.plan_list._names == []
    assert not server.called("plans_allowed")  # not even attempted without read:resources


def test_full_control_enables_queue_editing(app):
    app.connection.on_connect()
    settle(app, lambda: "full control" in app.window.connection_bar._access.cget("text"))
    settle(app, lambda: app.window.scheduler._buttons["start"].instate(["!disabled"]))
    assert app.window.scheduler._buttons["edit"].instate(["!disabled"])
