import pytest

from planrunner.plan_params import (
    Catalog,
    FieldKind,
    PlanInputError,
    build_item,
    describe_plan,
    form_values,
)

DEVICES = {
    "det1": {"is_readable": True, "is_movable": False, "is_flyable": False},
    "det2": {"is_readable": True, "is_movable": False, "is_flyable": False},
    "motor": {"is_readable": True, "is_movable": True, "is_flyable": False},
}
CATALOG = Catalog.from_allowed(DEVICES, plans=["count", "scan"])


def kw(name, **extra):
    return {"name": name, "kind": {"name": "POSITIONAL_OR_KEYWORD", "value": 1}, **extra}


# A description shaped like what the queueserver sends for a hextools-style plan.
TOMO = {
    "name": "tomo",
    "description": "Take a tomogram.",
    "parameters": [
        kw("detectors", description="The detectors."),  # concrete classes: annotation dropped
        kw("num_images", annotation={"type": "int"}, min="1"),
        kw("exposure_time", annotation={"type": "float"}, min="0", max="10"),
        kw("acquire_period", annotation={"type": "float | None"}, default="None"),
        kw("use_shutter", annotation={"type": "bool"}, default="True"),
        kw("sample_name", annotation={"type": "str | None"}, default="None"),
        kw("readers", annotation={"type": "list[__READABLE__]"}, default="()"),
        kw("mover", annotation={"type": "__MOVABLE__"}, default="None"),
        kw("mode", annotation={"type": "Modes", "enums": {"Modes": ["fast", "slow"]}},
           default="'fast'"),
        kw("md", annotation={"type": "dict | None"}, default="None"),
        {"name": "kwargs", "kind": {"name": "VAR_KEYWORD", "value": 4}},
    ],
}


@pytest.fixture
def spec():
    return describe_plan(TOMO, CATALOG)


def test_fields_match_types(spec):
    kinds = {p.name: p.field_kind for p in spec.params}
    assert kinds == {
        "detectors": FieldKind.EXPRESSION,
        "num_images": FieldKind.INTEGER,
        "exposure_time": FieldKind.FLOAT,
        "acquire_period": FieldKind.FLOAT,
        "use_shutter": FieldKind.BOOLEAN,
        "sample_name": FieldKind.STRING,
        "readers": FieldKind.MULTI_CHOICE,
        "mover": FieldKind.CHOICE,
        "mode": FieldKind.CHOICE,
        "md": FieldKind.EXPRESSION,
        "kwargs": FieldKind.EXPRESSION,
    }


def test_choices_come_from_device_flags_and_enums(spec):
    assert spec.param("readers").choices == ("det1", "det2", "motor")
    assert spec.param("mover").choices == ("motor",)
    assert spec.param("mode").choices == ("fast", "slow")


def test_unannotated_parameter_suggests_devices(spec):
    detectors = spec.param("detectors")
    assert detectors.required
    assert detectors.choices == ("det1", "det2", "motor")
    assert detectors.choices_are_suggestions


def test_initial_values_show_defaults(spec):
    assert spec.param("use_shutter").initial_value() is True
    assert spec.param("mode").initial_value() == "fast"
    assert spec.param("acquire_period").initial_value() == ""


def test_build_item_omits_defaults_and_empty_fields(spec):
    item = build_item(spec, {
        "detectors": "['det1', 'det2']",
        "num_images": "100",
        "exposure_time": "0.5",
        "use_shutter": True,  # equals the default
        "mode": "slow",
        "readers": ["det1"],
    })
    assert item == {
        "item_type": "plan",
        "name": "tomo",
        "kwargs": {
            "detectors": ["det1", "det2"],
            "num_images": 100,
            "exposure_time": 0.5,
            "mode": "slow",
            "readers": ["det1"],
        },
    }


def test_bare_device_name_is_passed_as_string(spec):
    item = build_item(spec, {"detectors": "det1", "num_images": "1", "exposure_time": "1"})
    assert item["kwargs"]["detectors"] == "det1"


def test_build_item_reports_every_bad_field(spec):
    with pytest.raises(PlanInputError) as info:
        build_item(spec, {"num_images": "0", "exposure_time": "fast", "mover": "det1"})
    assert info.value.errors == {
        "detectors": "required",
        "num_images": "must be >= 1",
        "exposure_time": "'fast' is not a number",
        "mover": "not allowed: det1",
    }


def test_var_keyword_merges_into_kwargs(spec):
    item = build_item(spec, {
        "detectors": "det1", "num_images": "1", "exposure_time": "1",
        "kwargs": "{'extra': 2}",
    })
    assert item["kwargs"]["extra"] == 2


def test_explicit_none_for_optional(spec):
    item = build_item(spec, {
        "detectors": "det1", "num_images": "1", "exposure_time": "1", "mover": "None",
    })
    assert "mover" not in item["kwargs"]  # None is the default, so it is omitted


def test_form_values_round_trip(spec):
    item = {
        "item_type": "plan",
        "name": "tomo",
        "args": [["det1"], 5],
        "kwargs": {"exposure_time": 0.1, "readers": ["det2"], "extra": 1},
        "item_uid": "abc",
    }
    values = form_values(spec, item)
    assert values["detectors"] == "['det1']"
    assert values["num_images"] == "5"
    assert values["exposure_time"] == "0.1"
    assert values["readers"] == ["det2"]
    assert values["use_shutter"] is True
    assert values["kwargs"] == "{'extra': 1}"
    rebuilt = build_item(spec, values)
    assert rebuilt["kwargs"] == {
        "detectors": ["det1"], "num_images": 5, "exposure_time": 0.1,
        "readers": ["det2"], "extra": 1,
    }


def test_positional_only_parameters_go_to_args():
    plan = {
        "name": "p",
        "parameters": [
            {"name": "a", "kind": {"name": "POSITIONAL_ONLY"}, "annotation": {"type": "int"}},
            {"name": "rest", "kind": {"name": "VAR_POSITIONAL"}},
        ],
    }
    spec = describe_plan(plan, CATALOG)
    assert build_item(spec, {"a": "1", "rest": "[2, 3]"})["args"] == [1, 2, 3]
