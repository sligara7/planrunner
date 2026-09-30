"""Read the annotation type strings the queueserver puts in ``plans_allowed``.

Examples of what arrives: ``"float"``, ``"float | None"``, ``"typing.Optional[int]"``,
``"list[__READABLE__]"``, ``"typing.List[typing.Union[Devices1, Enums1]]"``.
``parse_type`` reduces any of them to a ``TypeShape``: which names appear, and
whether the value is a list and whether ``None`` is allowed.
"""

import ast
from dataclasses import dataclass, field
from typing import Any

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
    literals: tuple[Any, ...] = ()
    """The allowed values of a ``Literal[...]`` (``None`` excluded)."""
    metadata: tuple[Any, ...] = ()
    """The extra arguments of an ``Annotated[type, ...]`` (e.g. units)."""


UNKNOWN = TypeShape(names=frozenset(), known=False)


def parse_type(type_str: str | None) -> TypeShape:
    if not type_str:
        return UNKNOWN
    try:
        tree = ast.parse(type_str, mode="eval").body
    except SyntaxError:
        return UNKNOWN

    found = _Found()
    tree = _unwrap_annotated(tree, found)
    is_list = False
    if isinstance(tree, ast.Subscript) and _name_of(tree.value) in _LIST_NAMES:
        is_list = True
        tree = tree.slice

    allows_none = _collect(tree, found)
    return TypeShape(names=frozenset(found.names), is_list=is_list, allows_none=allows_none,
                     literals=tuple(found.literals), metadata=tuple(found.metadata))


@dataclass(slots=True)
class _Found:
    names: set[str] = field(default_factory=set)
    literals: list[Any] = field(default_factory=list)
    metadata: list[Any] = field(default_factory=list)


def _unwrap_annotated(node: ast.expr, found: _Found) -> ast.expr:
    """``Annotated[float, "s"]`` -> ``float``, keeping ``"s"`` as metadata."""
    if isinstance(node, ast.Subscript) and _name_of(node.value) == "Annotated":
        first, *extra = _elements(node.slice)
        found.metadata.extend(_literal(e) for e in extra)
        return first
    return node


def _collect(node: ast.expr, found: _Found) -> bool:
    """Add the type names (and Literal values) under ``node``; return True if None is allowed."""
    node = _unwrap_annotated(node, found)  # also inside a union: Optional[Annotated[...]]
    match node:
        case ast.Constant(value=None):
            return True
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _collect(left, found) | _collect(right, found)
        case ast.Subscript(value=base) if _name_of(base) == "Literal":
            values = [_literal(e) for e in _elements(node.slice)]
            found.literals.extend(v for v in values if v is not None)
            return None in values
        case ast.Subscript(value=base) if _name_of(base) in _UNION_NAMES:
            allows_none = _name_of(base) == "Optional"
            for element in _elements(node.slice):
                allows_none |= _collect(element, found)
            return allows_none
        case ast.Subscript(value=base):
            # A generic other than a union, e.g. dict[str, float]: keep the outer name only.
            found.names.add(_name_of(base))
            return False
        case ast.Tuple(elts=elements):
            allows_none = False
            for element in elements:
                allows_none |= _collect(element, found)
            return allows_none
        case _:
            name = _name_of(node)
            if name in _NONE_NAMES:
                return True
            found.names.add(name)
            return False


def _literal(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except ValueError:
        return ast.unparse(node)


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
