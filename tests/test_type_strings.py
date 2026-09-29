import pytest

from planrunner.type_strings import parse_type


@pytest.mark.parametrize(
    ("text", "names", "is_list", "allows_none"),
    [
        ("float", {"float"}, False, False),
        ("float | None", {"float"}, False, True),
        ("typing.Optional[int]", {"int"}, False, True),
        ("typing.Union[int, float]", {"int", "float"}, False, False),
        ("list[__READABLE__]", {"__READABLE__"}, True, False),
        ("typing.List[typing.Union[Devices1, Enums1]]", {"Devices1", "Enums1"}, True, False),
        ("dict | None", {"dict"}, False, True),
        ("dict[str, float]", {"dict"}, False, False),
        ("typing.Union[str, NoneType]", {"str"}, False, True),
    ],
)
def test_parse_type(text, names, is_list, allows_none):
    shape = parse_type(text)
    assert shape.known
    assert shape.names == names
    assert shape.is_list is is_list
    assert shape.allows_none is allows_none


@pytest.mark.parametrize("text", [None, "", "list[", "<class 'x'>"])
def test_unreadable_types_are_unknown(text):
    assert not parse_type(text).known
