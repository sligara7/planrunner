"""Hidden dependencies and the generated plan <-> device map."""

from planrunner.device_map import build_map, device_index, render_markdown
from planrunner.hidden_deps import How, hidden_dependencies
from planrunner.plan_params import Catalog
from planrunner.sources import SourceFinder

PLAN_SOURCE = '''
def tomo_flyscan(detectors, exposure_time, panda=None, fe_shutter=None):
    det = kinetix1  # hard-coded despite 'detectors'
    panda = ensure_available(HDFPanda, panda=panda)
    shutter = get_obj_from_ipython_ns("photon_shutter", Shutter)
    for d in detectors:
        yield from bps.mv(d.acquire_time, exposure_time)
'''


def test_hidden_dependencies_are_found():
    found = hidden_dependencies(PLAN_SOURCE, ["kinetix1", "kinetix3", "detectors"])
    assert [(d.device, d.how) for d in found] == [
        ("kinetix1", How.GLOBAL),
        ("panda", How.LOOKUP_IF_NOT_PASSED),
        ("photon_shutter", How.LOOKUP),
    ]


def test_parameters_and_locals_are_not_hidden_dependencies():
    source = "def p(motor):\n    m = motor\n    yield from mv(m, 1)\n"
    assert hidden_dependencies(source, ["motor", "m"]) == []


def test_map_lists_fillable_devices_and_hidden_uses(tmp_path):
    startup = tmp_path / "startup"
    startup.mkdir()
    (startup / "85-fly.py").write_text(PLAN_SOURCE)
    plans = {"tomo_flyscan": {"name": "tomo_flyscan", "module": "__main__", "parameters": [
        {"name": "detectors", "kind": {"name": "POSITIONAL_OR_KEYWORD"}},
        {"name": "exposure_time", "kind": {"name": "POSITIONAL_OR_KEYWORD"}},
    ]}}
    devices = {"kinetix1": {"is_readable": True, "classname": "Kinetix"},
               "kinetix3": {"is_readable": True, "classname": "Kinetix"},
               "theta": {"is_readable": True, "is_movable": True, "classname": "Motor"}}
    catalog = Catalog.from_allowed(devices, plans=plans)
    maps = build_map(plans, catalog, SourceFinder([tmp_path]))
    (plan,) = maps
    rows = {r.name: r for r in plan.params}
    assert rows["detectors"].devices == ("kinetix1", "kinetix3")
    assert not rows["detectors"].declared
    assert rows["exposure_time"].devices == ()
    assert [d.device for d in plan.hidden] == ["kinetix1", "panda", "photon_shutter"]

    index = device_index(maps)
    assert index["kinetix1"].parameters == ["tomo_flyscan.detectors"]
    assert index["kinetix1"].hidden == ["tomo_flyscan"]

    report = render_markdown(maps, catalog, "http://sim")
    assert "2 of 2 parameters declare no type" in report
    assert "`kinetix1`: uses the profile's device directly" in report


def test_a_look_up_with_a_declared_device_default_is_not_hidden(tmp_path):
    (tmp_path / "fly.py").write_text(PLAN_SOURCE)
    plans = {"tomo_flyscan": {"name": "tomo_flyscan", "module": "__main__", "parameters": [
        {"name": "detectors", "kind": {"name": "POSITIONAL_OR_KEYWORD"}},
        {"name": "panda", "kind": {"name": "POSITIONAL_OR_KEYWORD"},
         "annotation": {"type": "__FLYABLE__ | None"}, "default": "'panda'",
         "default_defined_in_decorator": True},
    ]}}
    devices = {"panda": {"is_flyable": True}, "kinetix1": {"is_readable": True}}
    (plan,) = build_map(plans, Catalog.from_allowed(devices, plans=plans),
                        SourceFinder([tmp_path]))
    # panda: declared default, shown by the queueserver. photon_shutter: no parameter.
    assert [d.device for d in plan.hidden] == ["kinetix1", "photon_shutter"]
