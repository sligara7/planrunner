"""The operator's event trigger: which cameras qualify, and how it is sent."""

from fakes import FakeQueueServer, RecordingBus
from test_logic import ImmediateRunner

from planrunner.controllers.catalog import CatalogStore
from planrunner.controllers.commands import Commands
from planrunner.controllers.trigger import TriggerController
from planrunner.dispatch import ImmediateDispatcher
from planrunner.events import EventBus, Notice, PermissionsKnown, QueueUpdated, StatusUpdated
from planrunner.permissions import Permissions
from planrunner.plan_params import Catalog
from planrunner.triggers import TRIGGER_FUNCTION, trigger_targets


def _signals(*names):
    return {"components": {n: {"classname": "SignalRW"} for n in names}}


DEVICES = {
    "phantom": {"is_flyable": True, "classname": "PhantomDetector", "components": {
        "driver": _signals("acquire", "send_software_trigger")}},
    "kinetix1": {"is_flyable": True, "classname": "KinetixDetector", "components": {
        "driver": _signals("acquire", "acquire_time")}},
    "panda": {"is_flyable": True, "classname": "HDFPanda"},
}
CATALOG = Catalog.from_allowed(DEVICES, plans=[])
CAPTURE = {"name": "phantom_capture", "kwargs": {"camera": "phantom", "num_images": 5}}


def test_a_camera_with_a_software_trigger_in_the_running_item_is_a_target():
    fly = {"name": "tomo_flyscan", "args": [["kinetix1", "phantom"]], "kwargs": {"panda": "panda"}}
    assert trigger_targets(fly, CATALOG) == ("phantom",)
    assert trigger_targets(CAPTURE, CATALOG) == ("phantom",)


def test_nothing_running_or_no_trigger_camera_means_no_target():
    assert trigger_targets(None, CATALOG) == ()
    assert trigger_targets({"name": "tomo_flyscan", "kwargs": {"detectors": ["kinetix1"]}},
                           CATALOG) == ()


class FakeTriggerView:
    def __init__(self) -> None:
        self.targets: tuple[str, ...] = ()
        self.handler = None

    def set_trigger_handler(self, handler) -> None:
        self.handler = handler

    def show_trigger_targets(self, cameras) -> None:
        self.targets = cameras


def _controller(server: FakeQueueServer):
    bus = EventBus(ImmediateDispatcher())
    notices = RecordingBus()
    commands = Commands(ImmediateRunner(server), notices)
    catalog = CatalogStore(commands=commands, bus=bus)
    catalog.catalog = CATALOG
    view = FakeTriggerView()
    TriggerController(view=view, catalog=catalog, commands=commands, bus=bus)
    bus.subscribe(Notice, notices.publish)
    return bus, view, notices


def test_the_trigger_is_offered_only_while_the_plan_runs():
    bus, view, _ = _controller(FakeQueueServer())
    bus.publish(QueueUpdated(running_item=CAPTURE, items=()))
    assert view.targets == ()  # not running yet
    bus.publish(StatusUpdated({"manager_state": "executing_queue"}))
    assert view.targets == ("phantom",)
    bus.publish(StatusUpdated({"manager_state": "idle"}))
    assert view.targets == ()


def test_a_connection_that_may_not_execute_gets_no_trigger():
    bus, view, _ = _controller(FakeQueueServer())
    bus.publish(PermissionsKnown(Permissions.none()))
    bus.publish(QueueUpdated(running_item=CAPTURE, items=()))
    bus.publish(StatusUpdated({"manager_state": "executing_queue"}))
    assert view.targets == ()


def test_the_trigger_runs_the_profile_function_in_the_background():
    server = FakeQueueServer(task_reply={"success": True, "msg": "",
                                         "return_value": "Event trigger sent to phantom"})
    _, view, notices = _controller(server)
    view.handler("phantom")
    ((item,), kwargs), = server.called("function_execute")
    assert item == {"item_type": "function", "name": TRIGGER_FUNCTION, "args": ["phantom"]}
    assert kwargs == {"run_in_background": True}
    assert [n.text for n in notices.of_type(Notice)] == ["Event trigger sent to phantom"]


def test_a_failed_trigger_function_is_reported_as_an_error():
    server = FakeQueueServer(task_reply={"success": False, "msg": "'x' is not a camera"})
    _, view, notices = _controller(server)
    view.handler("x")
    (notice,) = notices.of_type(Notice)
    assert notice.is_error
    assert "'x' is not a camera" in notice.text
