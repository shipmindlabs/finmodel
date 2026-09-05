"""Calendar periods: twelve months rolled into quarters and a year."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Union

from finmodel.formula import Amount, NotApplicable, Value
from finmodel.spec import InputLine, SpecError, Statement

__all__ = [
    "MONTH",
    "QUARTER",
    "YEAR",
    "Carry",
    "IdentityError",
    "Period",
    "PeriodicModel",
    "Proof",
    "Results",
    "Rollup",
    "Timeline",
]

MONTH = "month"
QUARTER = "quarter"
YEAR = "year"

_KINDS = (MONTH, QUARTER, YEAR)

_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class Rollup(str, Enum):
    """How an input line answers for a span of periods rather than for one."""

    SUM = "sum"
    FIRST = "first"
    LAST = "last"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Period:
    """A span of whole months within one calendar year."""

    id: str
    label: str
    kind: str
    year: int
    first_month: int
    last_month: int

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise SpecError(f"unknown period kind {self.kind!r}")
        if not 1 <= self.first_month <= self.last_month <= 12:
            raise SpecError(f"period {self.id!r} does not span months of one year")

    @property
    def month_numbers(self) -> tuple[int, ...]:
        return tuple(range(self.first_month, self.last_month + 1))

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class Timeline:
    """One calendar year: twelve months, the quarters over them, the year itself."""

    year: int
    months: tuple[Period, ...] = field(init=False, repr=False, compare=False, default=())
    quarters: tuple[Period, ...] = field(
        init=False, repr=False, compare=False, default=()
    )
    _index: dict[str, Period] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        if not 1 <= self.year <= 9999:
            raise SpecError(f"year must be a calendar year, got {self.year}")
        months = tuple(
            Period(
                id=f"{self.year}-{number:02d}",
                label=f"{_MONTH_NAMES[number - 1]} {self.year}",
                kind=MONTH,
                year=self.year,
                first_month=number,
                last_month=number,
            )
            for number in range(1, 13)
        )
        quarters = tuple(
            Period(
                id=f"{self.year}-Q{number}",
                label=f"Q{number} {self.year}",
                kind=QUARTER,
                year=self.year,
                first_month=3 * number - 2,
                last_month=3 * number,
            )
            for number in range(1, 5)
        )
        object.__setattr__(self, "months", months)
        object.__setattr__(self, "quarters", quarters)
        object.__setattr__(self, "_index", {p.id: p for p in self.periods})

    @property
    def full_year(self) -> Period:
        return Period(
            id=str(self.year),
            label=f"FY {self.year}",
            kind=YEAR,
            year=self.year,
            first_month=1,
            last_month=12,
        )

    @property
    def periods(self) -> tuple[Period, ...]:
        """Every period the timeline computes, shortest span first."""
        return (*self.months, *self.quarters, self.full_year)

    def children(self, period: Period) -> tuple[Period, ...]:
        """What a span rolls up from: quarters for the year, months for a quarter."""
        if period.kind == YEAR:
            return self.quarters
        if period.kind == QUARTER:
            return tuple(
                month
                for month in self.months
                if period.first_month <= month.first_month <= period.last_month
            )
        return ()

    def period(self, period_id: str) -> Period:
        try:
            return self._index[period_id]
        except KeyError:
            raise SpecError(f"unknown period {period_id!r}") from None


PeriodRef = Union[Period, str]


@dataclass(frozen=True)
class Carry:
    """A balance that survives a boundary: this period's closing opens the next."""

    opening: str
    closing: str
    movement: str | None = None


@dataclass(frozen=True)
class Proof:
    """The opening/closing identity of one balance over one period."""

    period: Period
    balance: str
    opening: Amount
    movement: Amount
    closing: Amount

    @property
    def ok(self) -> bool:
        amounts = (self.opening, self.movement, self.closing)
        if any(isinstance(amount, NotApplicable) for amount in amounts):
            return False
        return self.opening + self.movement == self.closing

    def __str__(self) -> str:
        verdict = "holds" if self.ok else "fails"
        return (
            f"{self.balance} over {self.period.id}: "
            f"{self.opening} + {self.movement} = {self.closing} ({verdict})"
        )


class IdentityError(SpecError):
    """Raised when a closing balance is not its opening plus the period's movement."""

    def __init__(self, proof: Proof) -> None:
        self.proof = proof
        super().__init__(f"opening/closing identity fails: {proof}")


class Results:
    """Every period of a timeline, computed and proved."""

    def __init__(
        self,
        timeline: Timeline,
        frames: Mapping[str, Mapping[str, Amount]],
        proofs: Mapping[str, Sequence[Proof]],
    ) -> None:
        self._timeline = timeline
        self._frames = {key: dict(frame) for key, frame in frames.items()}
        self._proofs = {key: tuple(items) for key, items in proofs.items()}

    @property
    def timeline(self) -> Timeline:
        return self._timeline

    @property
    def periods(self) -> tuple[Period, ...]:
        return self._timeline.periods

    def __getitem__(self, period: PeriodRef) -> dict[str, Amount]:
        return dict(self._frames[self._id(period)])

    def amount(self, period: PeriodRef, line_id: str) -> Amount:
        """One line of one period."""
        frame = self._frames[self._id(period)]
        try:
            return frame[line_id]
        except KeyError:
            raise SpecError(f"unknown line {line_id!r}") from None

    def row(self, line_id: str) -> dict[str, Amount]:
        """One line across every period: months, then quarters, then the year."""
        return {period.id: self.amount(period, line_id) for period in self.periods}

    def proofs(self, period: PeriodRef | None = None) -> tuple[Proof, ...]:
        """The identity proofs of one period, or of the whole timeline."""
        if period is not None:
            return self._proofs[self._id(period)]
        return tuple(proof for item in self.periods for proof in self._proofs[item.id])

    def _id(self, period: PeriodRef) -> str:
        period_id = period.id if isinstance(period, Period) else period
        return self._timeline.period(period_id).id


@dataclass(frozen=True)
class PeriodicModel:
    """A statement computed period by period, with the balances that carry over."""

    statement: Statement
    carries: Sequence[Carry] = ()
    rollups: Mapping[str, Rollup | str] = field(default_factory=dict)
    _rollups: dict[str, Rollup] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "carries", tuple(self.carries))
        resolved: dict[str, Rollup] = {}
        for line_id, rollup in self.rollups.items():
            line = self.statement.line(line_id)
            if not isinstance(line, InputLine):
                raise SpecError(f"only input lines roll up, and {line_id!r} is computed")
            try:
                resolved[line_id] = Rollup(rollup)
            except ValueError:
                raise SpecError(
                    f"unknown rollup {rollup!r} for line {line_id!r}"
                ) from None
        object.__setattr__(self, "rollups", dict(self.rollups))

        seen: set[str] = set()
        for carry in self.carries:
            if carry.opening == carry.closing:
                raise SpecError(
                    f"balance {carry.opening!r} cannot open and close the same period"
                )
            if carry.opening in seen or carry.closing in seen:
                raise SpecError(f"balance {carry.closing!r} is carried twice")
            seen.update({carry.opening, carry.closing})
            opening = self.statement.line(carry.opening)
            if not isinstance(opening, InputLine):
                raise SpecError(
                    f"opening balance {carry.opening!r} must be an input line"
                )
            _claim(resolved, carry.opening, Rollup.FIRST)
            closing = self.statement.line(carry.closing)
            if isinstance(closing, InputLine):
                _claim(resolved, carry.closing, Rollup.LAST)
            if carry.movement is not None:
                self.statement.line(carry.movement)
        object.__setattr__(self, "_rollups", resolved)

    def rollup_of(self, line_id: str) -> Rollup:
        """How a line spans periods: a flow sums, a balance takes an edge."""
        self.statement.line(line_id)
        return self._rollups.get(line_id, Rollup.SUM)

    def run(
        self,
        timeline: Timeline,
        values: Mapping[str, Mapping[str, Value]],
        opening: Mapping[str, Value] | None = None,
    ) -> Results:
        """Compute the months in order, roll quarters and the year, prove balances."""
        self._check_periods(timeline, values)
        openings = dict(opening or {})
        unknown = sorted(set(openings) - {carry.opening for carry in self.carries})
        if unknown:
            raise SpecError(
                "opening balances given for lines that carry none: " + ", ".join(unknown)
            )

        frames: dict[str, dict[str, Amount]] = {}
        previous: dict[str, Amount] | None = None
        for month in timeline.months:
            given: dict[str, Value] = dict(values[month.id])
            for carry in self.carries:
                if carry.opening in given:
                    raise SpecError(
                        f"opening balance {carry.opening!r} is carried between "
                        f"periods, not given for {month.id}"
                    )
                given[carry.opening] = (
                    previous[carry.closing]
                    if previous is not None
                    else openings.get(carry.opening, Decimal(0))
                )
            previous = self.statement.evaluate(given)
            frames[month.id] = previous

        for quarter in timeline.quarters:
            frames[quarter.id] = self._roll(timeline.children(quarter), frames)
        frames[timeline.full_year.id] = self._roll(timeline.quarters, frames)

        proofs = {
            period.id: self._prove(period, frames[period.id])
            for period in timeline.periods
        }
        return Results(timeline, frames, proofs)

    def _check_periods(
        self, timeline: Timeline, values: Mapping[str, Mapping[str, Value]]
    ) -> None:
        expected = [month.id for month in timeline.months]
        missing = [period_id for period_id in expected if period_id not in values]
        if missing:
            raise SpecError("no values for " + ", ".join(missing))
        unexpected = sorted(set(values) - set(expected))
        if unexpected:
            raise SpecError(
                "values given for periods outside the timeline: " + ", ".join(unexpected)
            )

    def _roll(
        self, parts: Sequence[Period], frames: Mapping[str, Mapping[str, Amount]]
    ) -> dict[str, Amount]:
        # Only inputs roll up; computed lines are evaluated again over the rolled
        # inputs, so a ratio is the span's ratio and not a sum of ratios.
        gathered = [frames[part.id] for part in parts]
        rolled: dict[str, Value] = {
            line.id: _combine(
                self._rollups.get(line.id, Rollup.SUM),
                [frame[line.id] for frame in gathered],
            )
            for line in self.statement.input_lines
        }
        return self.statement.evaluate(rolled)

    def _prove(self, period: Period, frame: Mapping[str, Amount]) -> tuple[Proof, ...]:
        proofs: list[Proof] = []
        for carry in self.carries:
            if carry.movement is None:
                continue
            proof = Proof(
                period=period,
                balance=carry.closing,
                opening=frame[carry.opening],
                movement=frame[carry.movement],
                closing=frame[carry.closing],
            )
            if not proof.ok:
                raise IdentityError(proof)
            proofs.append(proof)
        return tuple(proofs)


def _claim(resolved: dict[str, Rollup], line_id: str, rollup: Rollup) -> None:
    stated = resolved.get(line_id)
    if stated is not None and stated is not rollup:
        raise SpecError(
            f"carried balance {line_id!r} rolls up as {rollup.value!r}, "
            f"not {stated.value!r}"
        )
    resolved[line_id] = rollup


def _combine(rollup: Rollup, amounts: Sequence[Amount]) -> Amount:
    if rollup is Rollup.FIRST:
        return amounts[0]
    if rollup is Rollup.LAST:
        return amounts[-1]
    total = Decimal(0)
    for amount in amounts:
        if isinstance(amount, NotApplicable):
            return amount
        total += amount
    return total
