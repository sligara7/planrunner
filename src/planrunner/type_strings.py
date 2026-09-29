"""Read the annotation type strings the queueserver puts in ``plans_allowed``.

Examples of what arrives: ``"float"``, ``"float | None"``, ``"typing.Optional[int]"``,
``"list[__READABLE__]"``, ``"typing.List[typing.Union[Devices1, Enums1]]"``.
``parse_type`` reduces any of them to a ``TypeShape``: which names appear, and
whether the value is a list and whether ``None`` is allowed.
"""

import ast
from dataclasses import dataclass

_LIST_NAMES = frozenset(
    {"list", "List", "tuple", "Tuple", "Sequence", "Iterable", "Collection", "set", "Set"}
)
_UNION_NAMES = frozenset({"Union", "Optional"})
_NONE_NAMES = frozenset({"None", "NoneType"})


@dataclass(frozen=True, slots=True)
class TypeShape:
    names: frozenset[str]
    """Every type name in the annotation, without module prefixes and without None."""
    is_list: bool = False
    """The outermost type is a list/sequence of the named types."""
    allows_none: bool = False
    known: bool = True
    """False when the string could not be read; treat the value as free text."""


UNKNOWN = TypeShape(names=frozenset(), known=False)


def parse_type(type_str: str | None) -> TypeShape:
    if not type_str:
        return UNKNOWN
    try:
        tree = ast.parse(type_str, mode="eval").body
    except SyntaxError:
        return UNKNOWN

    is_list = False
    if isinstance(tree, ast.Subscript) and _name_of(tree.value) in _LIST_NAMES:
        is_list = True
        tree = tree.slice

    names: set[str] = set()
    allows_none = _collect(tree, names)
    return TypeShape(names=frozenset(names), is_list=is_list, allows_none=allows_none)


def _collect(node: ast.expr, names: set[str]) -> bool:
    """Add the type names under ``node`` to ``names``; return True if None is allowed."""
    match node:
        case ast.Constant(value=None):
            return True
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _collect(left, names) | _collect(right, names)
        case ast.Subscript(value=base) if _name_of(base) in _UNION_NAMES:
            allows_none = _name_of(base) == "Optional"
            for element in _elements(node.slice):
                allows_none |= _collect(element, names)
            return allows_none
        case ast.Subscript(value=base):
            # A generic other than a union, e.g. dict[str, float]: keep the outer name only.
            names.add(_name_of(base))
            return False
        case ast.Tuple(elts=elements):
            allows_none = False
            for element in elements:
                allows_none |= _collect(element, names)
            return allows_none
        case _:
            name = _name_of(node)
            if name in _NONE_NAMES:
                return True
            names.add(name)
            return False


def _elements(node: ast.expr) -> list[ast.expr]:
    return list(node.elts) if isinstance(node, ast.Tuple) else [node]


def _name_of(node: ast.expr) -> str:
    """``typing.List`` -> ``List``; ``float`` -> ``float``; anything else -> its source."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case ast.Constant(value=None):
            return "None"
        case _:
            return ast.unparse(node)
