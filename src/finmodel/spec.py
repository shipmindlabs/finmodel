"""Declarative structure of a financial statement: blocks and lines."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Union

from finmodel.formula import (
    Amount,
    Expr,
    FormulaError,
    Rounding,
    Value,
    parse,
    to_amount,
)

__all__ = [
    "Block",
    "CircularReferenceError",
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


class CircularReferenceError(SpecError):
    """Raised when computed lines depend on one another in a cycle."""

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        super().__init__("circular reference: " + " -> ".join(self.cycle))


_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def formula_references(formula: str) -> tuple[str, ...]:
    """Return the line ids read by a formula, in order of first appearance."""
    return parse(formula).references


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
    rounding: Rounding | None = None

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
    expression: Expr = field(init=False, repr=False, compare=False)
    references: tuple[str, ...] = field(init=False, default=(), compare=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.formula.strip():
            raise SpecError(f"computed line {self.id!r} must have a formula")
        try:
            expression = parse(self.formula)
        except FormulaError as exc:
            raise SpecError(f"formula of {self.id!r} is invalid: {exc}") from exc
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "references", expression.references)


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
    rounding: Rounding | None = None
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

    @property
    def dependency_graph(self) -> dict[str, tuple[str, ...]]:
        """Direct dependencies of every line, keyed by line id."""
        return {line_id: _dependencies(self._lines, line_id) for line_id in self._lines}

    def line(self, line_id: str) -> Line:
        try:
            return self._lines[line_id]
        except KeyError:
            raise SpecError(f"unknown line {line_id!r}") from None

    def rounding_of(self, line_id: str) -> Rounding | None:
        """The rounding a line states, or the statement default it falls back to."""
        line = self.line(line_id)
        return line.rounding if line.rounding is not None else self.rounding

    def evaluate(self, values: Mapping[str, Value]) -> dict[str, Amount]:
        """Compute one period: input amounts in, every line rounded to its scale.

        A line that cannot be computed, such as a ratio over zero revenue, holds a
        `NotApplicable` that the lines reading it carry forward unchanged.
        """
        scope: dict[str, Amount] = {}
        for line in self.input_lines:
            if line.id not in values:
                raise SpecError(f"no value for input line {line.id!r}")
            scope[line.id] = self._round(line, values[line.id])
        unknown = sorted(set(values) - set(scope))
        if unknown:
            raise SpecError(
                "values given for lines that take none: " + ", ".join(unknown)
            )
        computed = {line.id: line for line in self.computed_lines}
        for line_id in self._order:
            line = computed[line_id]
            scope[line_id] = self._round(line, line.expression.evaluate(scope))
        return {line_id: scope[line_id] for line_id in self._lines}

    def _round(self, line: Line, value: Value) -> Amount:
        rounding = line.rounding if line.rounding is not None else self.rounding
        amount = to_amount(value, line.id)
        return rounding.apply(amount) if rounding is not None else amount


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


def _dependencies(lines: dict[str, Line], line_id: str) -> tuple[str, ...]:
    line = lines[line_id]
    return line.references if isinstance(line, ComputedLine) else ()


def _evaluation_order(lines: dict[str, Line]) -> tuple[str, ...]:
    """Topologically sort the computed lines over the graph of their references."""
    # The walk keeps its own stack: a chain of thousands of lines is a data
    # problem, not a reason to exhaust the interpreter stack.
    order: list[str] = []
    done: set[str] = set()

    for root in lines:
        if root in done:
            continue
        path = [root]
        active = {root}
        stack = [(root, iter(_dependencies(lines, root)))]
        while stack:
            line_id, pending = stack[-1]
            descended = False
            for ref in pending:
                if ref in done:
                    continue
                if ref in active:
                    raise CircularReferenceError(path[path.index(ref) :] + [ref])
                path.append(ref)
                active.add(ref)
                stack.append((ref, iter(_dependencies(lines, ref))))
                descended = True
                break
            if descended:
                continue
            stack.pop()
            path.pop()
            active.discard(line_id)
            done.add(line_id)
            if isinstance(lines[line_id], ComputedLine):
                order.append(line_id)
    return tuple(order)
