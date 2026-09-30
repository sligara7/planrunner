"""Parameter types read from a plan's local source, where the queueserver drops them."""

from planrunner.plan_params import Catalog, FieldKind, describe_plan
from planrunner.source_types import LocalSourceAnnotations, annotations_in
from planrunner.sources import SourceFinder

SOURCE = '''
def tomo_flyscan(
    detectors: list[KinetixDetector | PhantomDetector],
    num_images: int,
    panda: HDFPanda | None = None,
    stage=None,
):
    yield
'''

DEVICES = {
    "kinetix1": {"is_readable": True, "is_flyable": True, "classname": "KinetixDetector"},
    "kinetix3": {"is_readable": True, "is_flyable": True, "classname": "HEXKinetixDetector"},
    "phantom": {"is_readable": True, "is_flyable": True, "classname": "PhantomDetector"},
    "panda1": {"is_readable": True, "is_flyable": True, "classname": "HDFPanda"},
    "theta": {"is_readable": True, "is_movable": True, "classname": "Motor"},
}
CATALOG = Catalog.from_allowed(DEVICES, plans=["tomo_flyscan"])

# What the queueserver sends: class annotations dropped, builtins kept.
PLAN = {"name": "tomo_flyscan", "module": "hextools.tomography.flyscans", "parameters": [
    {"name": "detectors", "kind": {"name": "POSITIONAL_OR_KEYWORD"}},
    {"name": "num_images", "kind": {"name": "POSITIONAL_OR_KEYWORD"},
     "annotation": {"type": "int"}},
    {"name": "panda", "kind": {"name": "POSITIONAL_OR_KEYWORD"}, "default": "None"},
    {"name": "stage", "kind": {"name": "POSITIONAL_OR_KEYWORD"}, "default": "None"},
]}


def test_annotations_are_read_as_written():
    assert annotations_in(SOURCE) == {
        "detectors": "list[KinetixDetector | PhantomDetector]",
        "num_images": "int",
        "panda": "HDFPanda | None",
    }


def test_the_named_classes_pick_the_devices():
    spec = describe_plan(PLAN, CATALOG, annotations_in(SOURCE))
    detectors = spec.param("detectors")
    assert detectors.field_kind is FieldKind.MULTI_CHOICE
    # Exact class names only: HEXKinetixDetector's base class is not known here.
    assert detectors.choices == ("kinetix1", "phantom")
    assert detectors.type_label == "list[KinetixDetector | PhantomDetector] (from source)"
    panda = spec.param("panda")
    assert panda.field_kind is FieldKind.CHOICE
    assert panda.choices == ("panda1",)
    assert panda.allows_none


def test_without_a_source_type_the_parameter_is_guessed():
    spec = describe_plan(PLAN, CATALOG, annotations_in(SOURCE))
    assert spec.param("stage").type_label.endswith("?")


def test_a_source_type_naming_no_allowed_class_is_guessed():
    spec = describe_plan(PLAN, CATALOG, {"detectors": "list[PerkinElmerDetector]"})
    assert spec.param("detectors").type_label == "list[detector]?"


def test_a_type_the_server_sends_wins_over_the_source():
    spec = describe_plan(PLAN, CATALOG, {"num_images": "list[KinetixDetector]"})
    assert spec.param("num_images").field_kind is FieldKind.INTEGER


def test_local_source_is_found_by_plan_name_and_module(tmp_path):
    package = tmp_path / "hextools" / "tomography"
    package.mkdir(parents=True)
    (package / "flyscans.py").write_text(SOURCE)
    reader = LocalSourceAnnotations(SourceFinder([tmp_path]))
    assert reader.for_plan(PLAN)["detectors"] == "list[KinetixDetector | PhantomDetector]"
    assert reader.for_plan({**PLAN, "name": "missing"}) == {}
