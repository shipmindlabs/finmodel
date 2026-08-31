"""A formula language for computed lines: references, four operations, parentheses."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    DecimalException,
    InvalidOperation,
)
from typing import Union

__all__ = [
    "NA",
    "Amount",
    "BinaryOp",
    "Expr",
    "FormulaError",
    "NotApplicable",
    "Number",
    "Reference",
    "Rounding",
    "UnaryOp",
    "Value",
    "evaluate",
    "parse",
    "to_amount",
]


class FormulaError(ValueError):
    """Raised when a formula cannot be parsed or evaluated."""


@dataclass(frozen=True)
class NotApplicable:
    """An amount a line cannot have, carrying the reason it has none."""

    reason: str = "division by zero"

    def __str__(self) -> str:
        return f"n/a ({self.reason})"

    def __bool__(self) -> bool:
        return False


NA = NotApplicable()

Amount = Union[Decimal, NotApplicable]
Value = Union[Decimal, NotApplicable, int, float, str]
Scope = Mapping[str, Value]

ROUNDING_MODES = (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
)


@dataclass(frozen=True)
class Rounding:
    """A scale and a mode: how one line states its amounts."""

    digits: int
    mode: str = ROUND_HALF_UP

    def __post_init__(self) -> None:
        if self.mode not in ROUNDING_MODES:
            raise FormulaError(f"unknown rounding mode {self.mode!r}")

    @property
    def exponent(self) -> Decimal:
        """The quantum amounts are snapped to; negative digits round to units."""
        return Decimal(1).scaleb(-self.digits)

    def apply(self, amount: Amount) -> Amount:
        """Quantize an amount, leaving a stated non-answer untouched."""
        if isinstance(amount, NotApplicable):
            return amount
        try:
            return amount.quantize(self.exponent, rounding=self.mode)
        except InvalidOperation:
            raise FormulaError(
                f"cannot round {amount} to {self.digits} decimal places"
            ) from None


def to_amount(value: Value, name: str) -> Amount:
    """Coerce a scope value to an exact amount, or to the non-answer it already is."""
    if isinstance(value, (Decimal, NotApplicable)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, (float, str)):
        try:
            return Decimal(str(value))
        except DecimalException:
            raise FormulaError(f"value of {name!r} is not a number: {value!r}") from None
    raise FormulaError(f"value of {name!r} is not a number: {value!r}")


@dataclass(frozen=True)
class Number:
    """A literal amount."""

    value: Decimal

    @property
    def references(self) -> tuple[str, ...]:
        return ()

    def evaluate(self, scope: Scope) -> Amount:
        return self.value


@dataclass(frozen=True)
class Reference:
    """A read of another line, by id."""

    name: str

    @property
    def references(self) -> tuple[str, ...]:
        return (self.name,)

    def evaluate(self, scope: Scope) -> Amount:
        try:
            raw = scope[self.name]
        except KeyError:
            raise FormulaError(f"unbound reference {self.name!r}") from None
        return to_amount(raw, self.name)


@dataclass(frozen=True)
class UnaryOp:
    """A sign applied to an expression."""

    op: str
    operand: "Expr"

    @property
    def references(self) -> tuple[str, ...]:
        return self.operand.references

    def evaluate(self, scope: Scope) -> Amount:
        value = self.operand.evaluate(scope)
        if isinstance(value, NotApplicable):
            return value
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

    def evaluate(self, scope: Scope) -> Amount:
        left = self.left.evaluate(scope)
        if isinstance(left, NotApplicable):
            return left
        right = self.right.evaluate(scope)
        if isinstance(right, NotApplicable):
            return right
        if self.op == "+":
            return left + right
        if self.op == "-":
            return left - right
        if self.op == "*":
            return left * right
        if right == 0:
            return NA
        return left / right


Expr = Union[Number, Reference, UnaryOp, BinaryOp]


def parse(formula: str) -> Expr:
    """Parse a formula into an expression tree."""
    return _Parser(_tokenize(formula)).parse()


def evaluate(formula: Union[str, Expr], scope: Scope) -> Amount:
    """Evaluate a formula, or an already parsed expression, over a scope."""
    expression = parse(formula) if isinstance(formula, str) else formula
    return expression.evaluate(scope)


def _dedupe(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


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
