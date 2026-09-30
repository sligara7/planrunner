"""Plan grouping, source finding and the stop-run sequence."""

from fakes import FakeQueueServer, RecordingBus

from planrunner.controllers.commands import Commands
from planrunner.controllers.run_control import RunControl
from planrunner.dispatch import ImmediateDispatcher
from planrunner.events import EventBus, StatusUpdated
from planrunner.plan_groups import BEAMLINE, BLUESKY, HEXTOOLS, group_plans
from planrunner.protocols import Outcome
from planrunner.sources import SourceFinder


class ImmediateRunner:
    """A ``CallRunner`` that runs each call at once against a fake server."""

    def __init__(self, server) -> None:
        self.server = server

    def run(self, call, on_done=None) -> None:
        try:
            outcome = Outcome(value=call(self.server))
        except Exception as ex:
            outcome = Outcome(error=ex)
        if on_done:
            on_done(outcome)


def test_plans_are_grouped_by_source_beamline_first():
    plans = {
        "count": {"module": "bluesky.plans"},
        "tomo_flyscan": {"module": "__main__"},
        "take_radiograph": {"module": "hextools.tomography.radiography"},
        "sleep_for_secs": {},
    }
    groups = group_plans(plans)
    assert [(g.title, g.names) for g in groups] == [
        (BEAMLINE, ("sleep_for_secs", "tomo_flyscan")),
        (HEXTOOLS, ("take_radiograph",)),
        (BLUESKY, ("count",)),
    ]
    assert [g.names for g in group_plans(plans, "RADIO")] == [("take_radiograph",)]


def test_profile_plan_source_is_the_last_definition_in_load_order(tmp_path):
    startup = tmp_path / "profile" / "startup"
    startup.mkdir(parents=True)
    (startup / "10-old.py").write_text("def tomo_flyscan():\n    yield 'old'\n")
    (startup / "85-fly.py").write_text("x = 1\n\n\n@decorated\ndef tomo_flyscan(n):\n    yield n\n")
    source = SourceFinder([tmp_path / "profile"]).find("tomo_flyscan", "__main__")
    assert source is not None
    assert source.path.name == "85-fly.py"
    assert source.first_line == 4
    assert source.text.startswith("@decorated\ndef tomo_flyscan(n):")


def test_package_plan_source_is_found_under_src(tmp_path):
    module = tmp_path / "hextools" / "src" / "hextools" / "tomography"
    module.mkdir(parents=True)
    (module / "flyscans.py").write_text("def tomo_flyscan(detectors):\n    yield\n")
    source = SourceFinder([tmp_path / "hextools"]).find(
        "tomo_flyscan", "hextools.tomography.flyscans"
    )
    assert source is not None and source.path == module / "flyscans.py"


def test_installed_plan_source_is_found_without_a_root():
    source = SourceFinder([]).find("count", "bluesky.plans")
    assert source is not None and "def count(" in source.text


def test_missing_source_is_none(tmp_path):
    assert SourceFinder([tmp_path]).find("nothing", "__main__") is None


def test_stop_run_pauses_then_stops_once_paused():
    server = FakeQueueServer()
    bus = EventBus(ImmediateDispatcher())
    control = RunControl(commands=Commands(ImmediateRunner(server), RecordingBus()), bus=bus)

    bus.publish(StatusUpdated({"manager_state": "executing_queue"}))
    control.stop_run()
    assert server.called("re_pause") == [(("immediate",), {})]
    assert not server.called("re_stop")

    bus.publish(StatusUpdated({"manager_state": "paused"}))
    assert len(server.called("re_stop")) == 1
    bus.publish(StatusUpdated({"manager_state": "paused"}))
    assert len(server.called("re_stop")) == 1  # only once


def test_stop_run_when_already_paused_stops_directly():
    server = FakeQueueServer()
    bus = EventBus(ImmediateDispatcher())
    control = RunControl(commands=Commands(ImmediateRunner(server), RecordingBus()), bus=bus)
    bus.publish(StatusUpdated({"manager_state": "paused"}))
    control.stop_run()
    assert not server.called("re_pause")
    assert len(server.called("re_stop")) == 1
