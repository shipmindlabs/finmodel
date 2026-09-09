"""Checks: a sheet that balances and a cash line that reconciles, or the two numbers."""

from decimal import Decimal

import pytest

from finmodel import (
    Carry,
    Check,
    CheckError,
    Checklist,
    ComputedLine,
    InputLine,
    PeriodicModel,
    Rounding,
    SpecError,
    Statement,
    Timeline,
)


def sheet() -> Statement:
    return Statement(
        id="balance_sheet",
        label="Balance sheet",
        rounding=Rounding(2),
        children=[
            InputLine(id="cash", label="Cash"),
            InputLine(id="receivables", label="Receivables"),
            ComputedLine(
                id="total_assets", label="Total assets", formula="cash + receivables"
            ),
            InputLine(id="payables", label="Payables"),
            InputLine(id="equity", label="Equity"),
        ],
    )


def balances(tolerance: Decimal = Decimal(0)) -> Check:
    return Check.balances(
        assets="total_assets",
        liabilities="payables",
        equity="equity",
        tolerance=tolerance,
    )


def amounts(statement: Statement, equity: str = "1000") -> dict:
    return statement.evaluate(
        {
            "cash": Decimal("400"),
            "receivables": Decimal("800"),
            "payables": Decimal("200"),
            "equity": Decimal(equity),
        }
    )


def test_a_balanced_sheet_holds():
    statement = sheet()
    results = Checklist(statement, [balances()]).verify(amounts(statement))
    assert len(results) == 1
    assert results[0].ok
    assert results[0].difference == Decimal("0.00")


def test_a_failing_check_names_both_numbers():
    statement = sheet()
    with pytest.raises(CheckError) as error:
        Checklist(statement, [balances()]).verify(amounts(statement, equity="950"))
    result = error.value.result
    assert (result.left, result.right) == (Decimal("1200.00"), Decimal("1150.00"))
    assert result.difference == Decimal("50.00")
    assert str(error.value) == (
        "check failed: Balance sheet balances: total_assets 1200.00 "
        "vs payables + equity 1150.00 (off by 50.00)"
    )


def test_run_reports_without_refusing():
    statement = sheet()
    results = Checklist(statement, [balances()]).run(amounts(statement, equity="950"))
    assert not results[0].ok


def test_tolerance_absorbs_stated_drift():
    statement = sheet()
    values = amounts(statement, equity="999.95")
    assert Checklist(statement, [balances(Decimal("0.05"))]).run(values)[0].ok
    assert not Checklist(statement, [balances(Decimal("0.04"))]).run(values)[0].ok


def test_tolerance_must_not_be_negative():
    with pytest.raises(SpecError, match="non-negative"):
        Check(id="c", label="C", left="cash", right="equity", tolerance=Decimal("-1"))


def test_a_check_must_read_lines_the_statement_has():
    with pytest.raises(SpecError, match="unknown line 'goodwill'"):
        Checklist(sheet(), [Check(id="c", label="C", left="goodwill", right="equity")])


def test_duplicate_check_ids_are_refused():
    check = Check(id="same", label="Same", left="cash", right="equity")
    with pytest.raises(SpecError, match="duplicate check id 'same'"):
        Checklist(sheet(), [check, check])


def test_a_side_must_parse_and_must_not_be_empty():
    with pytest.raises(SpecError, match="left side of check 'c' is invalid"):
        Check(id="c", label="C", left="cash +", right="equity")
    with pytest.raises(SpecError, match="must have a right side"):
        Check(id="c", label="C", left="cash", right="   ")


def test_a_side_that_is_not_applicable_never_holds():
    statement = sheet()
    check = Check(id="ratio", label="Ratio", left="cash / 0", right="equity")
    result = Checklist(statement, [check]).run(amounts(statement))[0]
    assert not result.ok
    assert "n/a (division by zero)" in str(result)


def cash_model(cash: str = "opening_cash + receipts - payments") -> PeriodicModel:
    return PeriodicModel(
        Statement(
            id="cash_flow",
            label="Cash flow",
            rounding=Rounding(2),
            children=[
                InputLine(id="opening_cash", label="Opening cash"),
                InputLine(id="receipts", label="Receipts"),
                InputLine(id="payments", label="Payments"),
                ComputedLine(
                    id="net_cash_flow",
                    label="Net cash flow",
                    formula="receipts - payments",
                ),
                ComputedLine(
                    id="closing_cash",
                    label="Closing cash",
                    formula="opening_cash + net_cash_flow",
                ),
                ComputedLine(id="cash", label="Cash on hand", formula=cash),
            ],
        ),
        carries=[
            Carry(
                opening="opening_cash",
                closing="closing_cash",
                movement="net_cash_flow",
            )
        ],
    )


def monthly(timeline: Timeline) -> dict:
    return {
        month.id: {"receipts": Decimal(100 * number), "payments": Decimal("40")}
        for number, month in enumerate(timeline.months, start=1)
    }


def test_cash_reconciles_in_every_period():
    timeline = Timeline(2026)
    model = cash_model()
    results = model.run(timeline, monthly(timeline))
    checklist = Checklist(
        model.statement, [Check.reconciles(cash="cash", closing="closing_cash")]
    )
    checked = checklist.verify_periods(results)
    assert len(checked) == len(timeline.periods)
    assert all(result.ok for items in checked.values() for result in items)
    assert checked["2026-Q1"][0].right == results.amount("2026-Q1", "closing_cash")


def test_a_period_that_does_not_reconcile_is_named():
    timeline = Timeline(2026)
    model = cash_model("opening_cash + receipts - payments + 1")
    results = model.run(timeline, monthly(timeline))
    checklist = Checklist(
        model.statement, [Check.reconciles(cash="cash", closing="closing_cash")]
    )
    with pytest.raises(CheckError) as error:
        checklist.verify_periods(results)
    assert error.value.where == "2026-01"
    assert "over 2026-01" in str(error.value)
    assert error.value.result.difference == Decimal("1.00")
