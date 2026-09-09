"""Checks that a statement holds together: what must agree, and by how much."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from finmodel.formula import (
    Amount,
    Expr,
    FormulaError,
    NotApplicable,
    Value,
    parse,
    to_amount,
)
from finmodel.periods import Results
from finmodel.spec import SpecError, Statement

__all__ = ["Check", "CheckError", "CheckResult", "Checklist"]


class CheckError(SpecError):
    """Raised when the two sides of a check disagree."""

    def __init__(self, result: CheckResult, where: str | None = None) -> None:
        self.result = result
        self.where = where
        location = f" over {where}" if where is not None else ""
        super().__init__(f"check failed{location}: {result}")


@dataclass(frozen=True)
class Check:
    """Two sides of a statement that must agree, and the drift they may show."""

    id: str
    label: str
    left: str
    right: str
    tolerance: Decimal = Decimal(0)
    left_expression: Expr = field(init=False, repr=False, compare=False)
    right_expression: Expr = field(init=False, repr=False, compare=False)
    references: tuple[str, ...] = field(init=False, default=(), compare=False)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise SpecError(f"label of check {self.id!r} must not be empty")
        left = self._parse(self.left, "left")
        right = self._parse(self.right, "right")
        try:
            tolerance = to_amount(self.tolerance, self.id)
        except FormulaError as exc:
            raise SpecError(f"tolerance of check {self.id!r} is invalid: {exc}") from exc
        if not isinstance(tolerance, Decimal) or tolerance < 0:
            raise SpecError(
                f"tolerance of check {self.id!r} must be a non-negative amount"
            )
        object.__setattr__(self, "tolerance", tolerance)
        object.__setattr__(self, "left_expression", left)
        object.__setattr__(self, "right_expression", right)
        object.__setattr__(
            self,
            "references",
            tuple(dict.fromkeys((*left.references, *right.references))),
        )

    @classmethod
    def balances(
        cls,
        assets: str,
        liabilities: str,
        equity: str,
        *,
        id: str = "balance_sheet_balances",
        label: str = "Balance sheet balances",
        tolerance: Decimal = Decimal(0),
    ) -> "Check":
        """Assets against what funds them."""
        return cls(
            id=id,
            label=label,
            left=assets,
            right=f"{liabilities} + {equity}",
            tolerance=tolerance,
        )

    @classmethod
    def reconciles(
        cls,
        cash: str,
        closing: str,
        *,
        id: str = "cash_reconciles",
        label: str = "Cash reconciles",
        tolerance: Decimal = Decimal(0),
    ) -> "Check":
        """The cash line of a balance sheet against what the cash flow closes at."""
        return cls(id=id, label=label, left=cash, right=closing, tolerance=tolerance)

    def run(self, amounts: Mapping[str, Value]) -> "CheckResult":
        """Evaluate both sides over one period's amounts."""
        return CheckResult(
            self,
            self._side(self.left_expression, amounts),
            self._side(self.right_expression, amounts),
        )

    def _parse(self, formula: str, side: str) -> Expr:
        if not formula.strip():
            raise SpecError(f"check {self.id!r} must have a {side} side")
        try:
            return parse(formula)
        except FormulaError as exc:
            raise SpecError(
                f"{side} side of check {self.id!r} is invalid: {exc}"
            ) from exc

    def _side(self, expression: Expr, amounts: Mapping[str, Value]) -> Amount:
        try:
            return expression.evaluate(amounts)
        except FormulaError as exc:
            raise SpecError(f"check {self.id!r} cannot run: {exc}") from exc


@dataclass(frozen=True)
class CheckResult:
    """What a check found: the two amounts, and whether they agree."""

    check: Check
    left: Amount
    right: Amount

    @property
    def difference(self) -> Amount:
        if isinstance(self.left, NotApplicable):
            return self.left
        if isinstance(self.right, NotApplicable):
            return self.right
        return self.left - self.right

    @property
    def ok(self) -> bool:
        difference = self.difference
        if isinstance(difference, NotApplicable):
            return False
        return abs(difference) <= self.check.tolerance

    def __str__(self) -> str:
        difference = self.difference
        if isinstance(difference, NotApplicable):
            verdict = str(difference)
        elif self.ok:
            verdict = "holds"
        else:
            verdict = f"off by {difference}"
        return (
            f"{self.check.label}: {self.check.left} {self.left} "
            f"vs {self.check.right} {self.right} ({verdict})"
        )


@dataclass(frozen=True)
class Checklist:
    """The checks a statement must pass, bound to the lines they read."""

    statement: Statement
    checks: Sequence[Check] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        seen: set[str] = set()
        for check in self.checks:
            if check.id in seen:
                raise SpecError(f"duplicate check id {check.id!r}")
            seen.add(check.id)
            for reference in check.references:
                self.statement.line(reference)

    def run(self, amounts: Mapping[str, Value]) -> tuple[CheckResult, ...]:
        """Run every check over one period's amounts, in declaration order."""
        return tuple(check.run(amounts) for check in self.checks)

    def verify(
        self, amounts: Mapping[str, Value], where: str | None = None
    ) -> tuple[CheckResult, ...]:
        """Run every check and refuse the period on the first one that fails.

        `where` names the period the amounts belong to, for the error message.
        """
        results = self.run(amounts)
        for result in results:
            if not result.ok:
                raise CheckError(result, where)
        return results

    def verify_periods(self, results: Results) -> dict[str, tuple[CheckResult, ...]]:
        """Verify every period of a computed timeline, keyed by period id."""
        return {
            period.id: self.verify(results[period], period.id)
            for period in results.periods
        }
