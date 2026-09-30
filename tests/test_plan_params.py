import inspect

import pytest

from planrunner.plan_params import (
    Catalog,
    FieldKind,
    PlanInputError,
    build_item,
    describe_plan,
    form_values,
    name_conversion_warnings,
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
        "detectors": FieldKind.MULTI_CHOICE,
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


def test_untyped_detectors_parameter_offers_only_detectors(spec):
    detectors = spec.param("detectors")
    assert detectors.required
    assert detectors.field_kind is FieldKind.MULTI_CHOICE
    assert detectors.type_label == "list[detector]?"
    assert detectors.choices == ("det1", "det2")  # not the motor


def test_untyped_parameters_are_guessed_not_offered_devices():
    """count_germ(count_time, num=1, detector=None, md=None): AJ's screenshot."""
    catalog = Catalog.from_allowed(
        {**DEVICES, "ph_close_cmd": {"is_readable": True, "is_movable": True}}, plans=[])
    plan = {"name": "count_germ", "parameters": [
        kw("count_time"), kw("num", default="1"), kw("detector", default="None"),
        kw("md", default="None"), kw("rot_motor", default="None"), kw("mystery")]}
    params = {p.name: p for p in describe_plan(plan, catalog).params}
    assert (params["count_time"].field_kind, params["count_time"].type_label) == (
        FieldKind.FLOAT, "float?")
    assert params["count_time"].choices == ()
    assert (params["num"].field_kind, params["num"].type_label) == (FieldKind.INTEGER, "int?")
    assert params["detector"].field_kind is FieldKind.CHOICE
    assert params["detector"].choices == ("det1", "det2")  # no motor, no command PV
    assert params["md"].type_label == "dict?"
    assert params["rot_motor"].choices == ("motor", "ph_close_cmd")
    assert (params["mystery"].field_kind, params["mystery"].choices) == (FieldKind.EXPRESSION, ())


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


def test_bare_device_name_is_passed_as_string():
    spec = describe_plan({"name": "p", "parameters": [kw("thing")]}, CATALOG)
    assert build_item(spec, {"thing": "det1"})["kwargs"]["thing"] == "det1"


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
    assert values["detectors"] == ["det1"]
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


def test_text_that_names_a_device_is_flagged_for_untyped_parameters():
    plan = {"name": "p", "parameters": [
        kw("sample_name"), kw("note", annotation={"type": "str"}), kw("options"),
        kw("detector", default="None")]}
    spec = describe_plan(plan, CATALOG)
    item = build_item(spec, {
        "sample_name": "motor",                        # untyped: would become the motor
        "note": "motor",                               # typed str: left as text
        "options": "{'target': 'det1.stats', 'n': 3}",  # nested dotted path
        "detector": "det1",                            # a device picker: intended
    })
    warnings = name_conversion_warnings(spec, item, CATALOG)
    assert set(warnings) == {"sample_name", "options"}
    assert "'motor'" in warnings["sample_name"]
    assert "'det1.stats'" in warnings["options"]


def test_plain_text_is_not_flagged():
    spec = describe_plan({"name": "p", "parameters": [kw("sample_name")]}, CATALOG)
    item = build_item(spec, {"sample_name": "my_sample_3"})
    assert name_conversion_warnings(spec, item, CATALOG) == {}


TREE_DEVICES = {
    "theta": {"is_readable": True, "is_movable": True, "classname": "EpicsMotor", "components": {
        "user_readback": {"is_readable": True, "is_movable": True, "classname": "EpicsSignalRO"},
        "user_setpoint": {"is_readable": True, "is_movable": True, "classname": "EpicsSignal"},
    }},
    "det1": {"is_readable": True, "classname": "Det", "components": {
        "exposure": {"is_readable": True, "is_movable": True, "classname": "SignalRW"}}},
}


def test_movable_picker_offers_settable_components_only():
    catalog = Catalog.from_allowed(TREE_DEVICES, plans=[])
    spec = describe_plan({"name": "p", "parameters": [
        kw("motor", annotation={"type": "__MOVABLE__"})]}, catalog)
    motor = spec.param("motor")
    assert motor.device_capability == "movable"
    assert motor.component_choices == {"theta": ("theta.user_setpoint",)}  # not the RO readback
    item = build_item(spec, {"motor": "theta.user_setpoint"})
    assert item["kwargs"]["motor"] == "theta.user_setpoint"
    with pytest.raises(PlanInputError):
        build_item(spec, {"motor": "theta.user_readback"})


def test_literal_parameter_is_a_choice_that_sends_the_typed_value():
    spec = describe_plan({"name": "p", "parameters": [
        kw("mode", annotation={"type": "typing.Literal['ellipse', 'linear']"}, default="'ellipse'"),
        kw("binning", annotation={"type": "typing.Literal[1, 2, 4]"}, default="1"),
        kw("exposure", annotation={"type": "typing.Annotated[float, 's']"})]}, CATALOG)
    assert spec.param("mode").field_kind is FieldKind.CHOICE
    assert spec.param("mode").choices == ("ellipse", "linear")
    assert spec.param("binning").choices == ("1", "2", "4")
    assert spec.param("exposure").type_label == "float, s"
    item = build_item(spec, {"mode": "linear", "binning": "4", "exposure": "0.5"})
    assert item["kwargs"] == {"mode": "linear", "binning": 4, "exposure": 0.5}
    assert form_values(spec, item)["binning"] == "4"


SCAN = {"name": "scan", "parameters": [
    kw("detectors", annotation={"type": "collections.abc.Sequence[__READABLE__]"}),
    {"name": "args", "kind": {"name": "VAR_POSITIONAL"}},
    {"name": "num", "kind": {"name": "KEYWORD_ONLY"}, "annotation": {"type": "int | None"},
     "default": "None"}]}


def test_scan_args_become_motor_rows():
    catalog = Catalog.from_allowed(TREE_DEVICES, plans=[])
    spec = describe_plan(SCAN, catalog)
    rows = spec.param("args")
    assert rows.field_kind is FieldKind.DEVICE_ROWS
    assert [c.name for c in rows.row_columns] == ["motor", "start", "stop"]
    item = build_item(spec, {"detectors": ["det1"], "args": "['theta', 0.0, 10.0]", "num": "5"})
    # detectors must be positional once *args is filled, or 'theta' would bind to it
    assert item == {
        "item_type": "plan", "name": "scan",
        "args": [["det1"], "theta", 0.0, 10.0],
        "kwargs": {"num": 5},
    }
    assert form_values(spec, item)["args"] == "['theta', 0.0, 10.0]"


def test_calling_the_built_item_binds_like_python():
    """The item must bind to the real signature exactly as the worker will call it."""
    def scan(detectors, *args, num=None, md=None):
        yield None

    catalog = Catalog.from_allowed(TREE_DEVICES, plans=[])
    spec = describe_plan(SCAN, catalog)
    item = build_item(spec, {"detectors": ["det1"], "args": "['theta', 0, 1]", "num": "3"})
    bound = inspect.signature(scan).bind(*item["args"], **item["kwargs"])
    assert bound.arguments["detectors"] == ["det1"]
    assert bound.arguments["args"] == ("theta", 0, 1)
    assert name_conversion_warnings(spec, item, catalog) == {}  # motors are intended


def test_bad_rows_are_reported_by_row_and_column():
    catalog = Catalog.from_allowed(TREE_DEVICES, plans=[])
    spec = describe_plan(SCAN, catalog)
    with pytest.raises(PlanInputError) as info:
        build_item(spec, {"detectors": ["det1"], "args": "['theta', 0.0, 'far']"})
    assert info.value.errors["args"] == "row 1, stop: 'far' is not a number"
    with pytest.raises(PlanInputError) as info:
        build_item(spec, {"detectors": ["det1"], "args": "['det1', 0, 1]"})
    assert "not an allowed movable device" in info.value.errors["args"]
