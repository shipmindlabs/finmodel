"""A formula language for computed lines: references, four operations, parentheses."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Union

__all__ = [
    "BinaryOp",
    "Expr",
    "FormulaError",
    "Number",
    "Reference",
    "UnaryOp",
    "Value",
    "evaluate",
    "parse",
]


class FormulaError(ValueError):
    """Raised when a formula cannot be parsed or evaluated."""


Value = Union[Decimal, int, float]
Scope = Mapping[str, Value]


@dataclass(frozen=True)
class Number:
    """A literal amount."""

    value: Decimal

    @property
    def references(self) -> tuple[str, ...]:
        return ()

    def evaluate(self, scope: Scope) -> Decimal:
        return self.value


@dataclass(frozen=True)
class Reference:
    """A read of another line, by id."""

    name: str

    @property
    def references(self) -> tuple[str, ...]:
        return (self.name,)

    def evaluate(self, scope: Scope) -> Decimal:
        try:
            raw = scope[self.name]
        except KeyError:
            raise FormulaError(f"unbound reference {self.name!r}") from None
        return _to_decimal(raw, self.name)


@dataclass(frozen=True)
class UnaryOp:
    """A sign applied to an expression."""

    op: str
    operand: "Expr"

    @property
    def references(self) -> tuple[str, ...]:
        return self.operand.references

    def evaluate(self, scope: Scope) -> Decimal:
        value = self.operand.evaluate(scope)
        return -value if self.op == "-" else value


@dataclass(frozen=True)
class BinaryOp:
    """One of the four arithmetic operations."""

    op: str
    left: "Expr"
    right: "Expr"

    @property
    def references(self) -> tuple[str, ...]:
        return _dedupe((*self.left.references, *self.right.references))

    def evaluate(self, scope: Scope) -> Decimal:
        left = self.left.evaluate(scope)
        right = self.right.evaluate(scope)
        if self.op == "+":
            return left + right
        if self.op == "-":
            return left - right
        if self.op == "*":
            return left * right
        if right == 0:
            raise FormulaError("division by zero")
        return left / right


Expr = Union[Number, Reference, UnaryOp, BinaryOp]


def parse(formula: str) -> Expr:
    """Parse a formula into an expression tree."""
    return _Parser(_tokenize(formula)).parse()


def evaluate(formula: Union[str, Expr], scope: Scope) -> Decimal:
    """Evaluate a formula, or an already parsed expression, over a scope."""
    expression = parse(formula) if isinstance(formula, str) else formula
    return expression.evaluate(scope)


def _dedupe(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _to_decimal(value: Value, name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise FormulaError(f"value of {name!r} is not a number: {value!r}")


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    position: int


_TOKEN_RE = re.compile(
    r"(?P<number>\d+(?:\.\d*)?|\.\d+)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>[-+*/()])"
)


def _tokenize(formula: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(formula):
        if formula[position].isspace():
            position += 1
            continue
        match = _TOKEN_RE.match(formula, position)
        if match is None:
            raise FormulaError(
                f"unexpected character {formula[position]!r} at position {position}"
            )
        tokens.append(_Token(str(match.lastgroup), match.group(), position))
        position = match.end()
    tokens.append(_Token("end", "", len(formula)))
    return tokens


class _Parser:
    """Recursive descent over the grammar of sums, products and atoms."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._position = 0

    def parse(self) -> Expr:
        expression = self._sum()
        token = self._current
        if token.kind != "end":
            raise FormulaError(f"unexpected {token.text!r} at position {token.position}")
        return expression

    @property
    def _current(self) -> _Token:
        return self._tokens[self._position]

    def _advance(self) -> _Token:
        token = self._current
        self._position += 1
        return token

    def _at_operator(self, operators: str) -> bool:
        token = self._current
        return token.kind == "op" and token.text in operators

    def _sum(self) -> Expr:
        node = self._product()
        while self._at_operator("+-"):
            op = self._advance().text
            node = BinaryOp(op, node, self._product())
        return node

    def _product(self) -> Expr:
        node = self._signed()
        while self._at_operator("*/"):
            op = self._advance().text
            node = BinaryOp(op, node, self._signed())
        return node

    def _signed(self) -> Expr:
        if self._at_operator("+-"):
            op = self._advance().text
            return UnaryOp(op, self._signed())
        return self._atom()

    def _atom(self) -> Expr:
        token = self._advance()
        if token.kind == "number":
            try:
                return Number(Decimal(token.text))
            except DecimalException:
                raise FormulaError(
                    f"invalid number {token.text!r} at position {token.position}"
                ) from None
        if token.kind == "name":
            return Reference(token.text)
        if token.kind == "op" and token.text == "(":
            node = self._sum()
            closing = self._advance()
            if closing.kind != "op" or closing.text != ")":
                raise FormulaError(f"expected ')' at position {closing.position}")
            return node
        if token.kind == "end":
            raise FormulaError("unexpected end of formula")
        raise FormulaError(f"unexpected {token.text!r} at position {token.position}")
