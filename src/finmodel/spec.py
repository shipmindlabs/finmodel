"""Declarative structure of a financial statement: blocks and lines."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Union

__all__ = [
    "Block",
    "ComputedLine",
    "InputLine",
    "Line",
    "Node",
    "SpecError",
    "Statement",
    "formula_references",
]


class SpecError(ValueError):
    """Raised when a statement spec is structurally invalid."""


_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_NAME_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<call>\()?")


def formula_references(formula: str) -> tuple[str, ...]:
    """Return the line ids read by a formula, in order of first appearance."""
    # A name directly followed by "(" is a function call, not a line reference.
    seen: dict[str, None] = {}
    for match in _NAME_RE.finditer(formula):
        if match.group("call") is None:
            seen.setdefault(match.group("name"), None)
    return tuple(seen)


def _validate_id(value: str, kind: str) -> None:
    if not _ID_RE.match(value):
        raise SpecError(f"{kind} id must be an identifier, got {value!r}")


def _validate_label(value: str, node_id: str) -> None:
    if not value.strip():
        raise SpecError(f"label of {node_id!r} must not be empty")


@dataclass(frozen=True)
class Line:
    """A single row of a statement."""

    id: str
    label: str

    def __post_init__(self) -> None:
        _validate_id(self.id, "line")
        _validate_label(self.label, self.id)


@dataclass(frozen=True)
class InputLine(Line):
    """A row whose values are supplied per period."""

    unit: str | None = None


@dataclass(frozen=True)
class ComputedLine(Line):
    """A row whose values are derived from other lines through a formula."""

    formula: str = ""
    references: tuple[str, ...] = field(init=False, default=(), compare=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.formula.strip():
            raise SpecError(f"computed line {self.id!r} must have a formula")
        object.__setattr__(self, "references", formula_references(self.formula))


@dataclass(frozen=True)
class Block:
    """A named group of lines and nested blocks, such as a category."""

    id: str
    label: str
    children: Sequence["Node"] = ()

    def __post_init__(self) -> None:
        _validate_id(self.id, "block")
        _validate_label(self.label, self.id)
        object.__setattr__(self, "children", tuple(self.children))
        if not self.children:
            raise SpecError(f"block {self.id!r} must contain at least one child")

    def walk(self, depth: int = 0) -> Iterator[tuple["Node", int]]:
        return _walk(self.children, depth)


Node = Union[Block, Line]


def _walk(nodes: Sequence[Node], depth: int) -> Iterator[tuple[Node, int]]:
    for node in nodes:
        yield node, depth
        if isinstance(node, Block):
            yield from _walk(node.children, depth + 1)


@dataclass(frozen=True)
class Statement:
    """A whole statement: the tree that renders, computes and validates."""

    id: str
    label: str
    children: Sequence[Node] = ()
    _lines: dict[str, Line] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _order: tuple[str, ...] = field(init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        _validate_id(self.id, "statement")
        _validate_label(self.label, self.id)
        object.__setattr__(self, "children", tuple(self.children))
        if not self.children:
            raise SpecError(f"statement {self.id!r} must contain at least one child")
        blocks, lines = _index(self.children)
        _validate_references(blocks, lines)
        object.__setattr__(self, "_lines", lines)
        object.__setattr__(self, "_order", _evaluation_order(lines))

    def walk(self, depth: int = 0) -> Iterator[tuple[Node, int]]:
        """Yield every node with its nesting depth, in declaration order."""
        return _walk(self.children, depth)

    @property
    def lines(self) -> tuple[Line, ...]:
        return tuple(self._lines.values())

    @property
    def input_lines(self) -> tuple[InputLine, ...]:
        return tuple(x for x in self._lines.values() if isinstance(x, InputLine))

    @property
    def computed_lines(self) -> tuple[ComputedLine, ...]:
        return tuple(x for x in self._lines.values() if isinstance(x, ComputedLine))

    @property
    def evaluation_order(self) -> tuple[str, ...]:
        """Ids of the computed lines, dependencies first."""
        return self._order

    def line(self, line_id: str) -> Line:
        try:
            return self._lines[line_id]
        except KeyError:
            raise SpecError(f"unknown line {line_id!r}") from None


def _index(children: Sequence[Node]) -> tuple[dict[str, Block], dict[str, Line]]:
    blocks: dict[str, Block] = {}
    lines: dict[str, Line] = {}
    for node, _ in _walk(children, 0):
        if node.id in blocks or node.id in lines:
            raise SpecError(f"duplicate id {node.id!r}")
        if isinstance(node, Block):
            blocks[node.id] = node
        else:
            lines[node.id] = node
    return blocks, lines


def _validate_references(blocks: dict[str, Block], lines: dict[str, Line]) -> None:
    for line in lines.values():
        if not isinstance(line, ComputedLine):
            continue
        for ref in line.references:
            if ref in lines:
                continue
            if ref in blocks:
                raise SpecError(
                    f"line {line.id!r} references block {ref!r}; "
                    "formulas may only reference lines"
                )
            raise SpecError(f"line {line.id!r} references unknown line {ref!r}")


def _evaluation_order(lines: dict[str, Line]) -> tuple[str, ...]:
    order: list[str] = []
    done: set[str] = set()
    active: list[str] = []

    def visit(line_id: str) -> None:
        if line_id in done:
            return
        if line_id in active:
            cycle = active[active.index(line_id) :] + [line_id]
            raise SpecError("circular reference: " + " -> ".join(cycle))
        line = lines[line_id]
        if isinstance(line, ComputedLine):
            active.append(line_id)
            for ref in line.references:
                visit(ref)
            active.pop()
            order.append(line_id)
        done.add(line_id)

    for line_id in lines:
        visit(line_id)
    return tuple(order)
