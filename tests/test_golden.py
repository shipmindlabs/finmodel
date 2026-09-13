"""Golden statements: worked examples against the numbers kept on file."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finmodel import CheckError, Timeline

GOLDEN = Path(__file__).parent / "golden"


def load(name: str) -> dict:
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def given(values: dict) -> dict:
    return {line: Decimal(amount) for line, amount in values.items()}


def shown(frame: dict) -> dict:
    return {line: str(amount) for line, amount in frame.items()}


PNL = load("saas_pnl")
CASH = load("cash_flow_2026")
SHEET = load("balance_sheet_2026")


def run_cash(model):
    timeline = Timeline(CASH["year"])
    months = {month: given(values) for month, values in CASH["months"].items()}
    return timeline, model.run(timeline, months, opening=given(CASH["opening"]))


@pytest.mark.parametrize("case", PNL["cases"], ids=lambda case: case["name"])
def test_profit_and_loss_matches_the_golden_file(pnl_statement, case):
    amounts = pnl_statement.evaluate(given(case["inputs"]))
    assert list(amounts) == list(case["expected"])
    assert shown(amounts) == case["expected"]


def test_the_cash_flow_year_matches_the_golden_file(cash_flow_model):
    timeline, results = run_cash(cash_flow_model)
    assert list(CASH["expected"]) == [period.id for period in timeline.periods]
    for period_id, expected in CASH["expected"].items():
        assert shown(results[period_id]) == expected, period_id


def test_every_period_of_the_cash_flow_proves_its_identity(cash_flow_model):
    timeline, results = run_cash(cash_flow_model)
    proofs = results.proofs()
    assert len(proofs) == len(timeline.periods)
    assert all(proof.ok for proof in proofs)
    assert str(results.proofs("2026")[0]) == (
        "closing_cash over 2026: 500.00 + 7080.00 = 7580.00 (holds)"
    )


def test_the_balance_sheet_matches_the_golden_file(balance_sheet_statement):
    amounts = balance_sheet_statement.evaluate(given(SHEET["inputs"]))
    assert list(amounts) == list(SHEET["expected"])
    assert shown(amounts) == SHEET["expected"]


def test_the_balance_sheet_holds_together(balance_sheet_books, balance_sheet_statement):
    amounts = balance_sheet_statement.evaluate(given(SHEET["inputs"]))
    results = balance_sheet_books.verify(amounts)
    assert [result.check.id for result in results] == [
        "balance_sheet_balances",
        "funding_adds_up",
    ]
    assert all(result.difference == Decimal(0) for result in results)


def test_a_sheet_that_stops_balancing_is_refused(
    balance_sheet_books, balance_sheet_statement
):
    inputs = given(SHEET["inputs"])
    inputs["retained_earnings"] += Decimal(25)
    amounts = balance_sheet_statement.evaluate(inputs)
    with pytest.raises(CheckError) as error:
        balance_sheet_books.verify(amounts)
    assert error.value.result.check.id == "balance_sheet_balances"
    assert error.value.result.difference == Decimal("-25.00")


def test_the_sheet_cash_is_what_the_year_closed_at(
    balance_sheet_statement, cash_flow_model
):
    _, results = run_cash(cash_flow_model)
    amounts = balance_sheet_statement.evaluate(given(SHEET["inputs"]))
    assert amounts["cash"] == results.amount("2026", "closing_cash")
