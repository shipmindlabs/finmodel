"""Twelve months into quarters and a year: rollups, carries and the identity."""

from decimal import Decimal

import pytest

from finmodel import (
    Carry,
    ComputedLine,
    IdentityError,
    InputLine,
    NotApplicable,
    PeriodicModel,
    Proof,
    Rollup,
    Rounding,
    SpecError,
    Statement,
    Timeline,
)


def cash_statement(closing: str = "opening_cash + net_cash_flow") -> Statement:
    return Statement(
        id="cash",
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
            ComputedLine(id="closing_cash", label="Closing cash", formula=closing),
        ],
    )


def cash_model(closing: str = "opening_cash + net_cash_flow") -> PeriodicModel:
    return PeriodicModel(
        cash_statement(closing),
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


@pytest.fixture
def timeline() -> Timeline:
    return Timeline(2026)


@pytest.fixture
def results(timeline):
    return cash_model().run(
        timeline, monthly(timeline), opening={"opening_cash": Decimal("1000")}
    )


def test_timeline_has_twelve_months(timeline):
    assert [month.id for month in timeline.months][:2] == ["2026-01", "2026-02"]
    assert len(timeline.months) == 12
    assert timeline.months[0].label == "January 2026"
    assert timeline.months[-1].id == "2026-12"


def test_quarters_cover_their_months(timeline):
    assert [q.id for q in timeline.quarters] == [
        "2026-Q1",
        "2026-Q2",
        "2026-Q3",
        "2026-Q4",
    ]
    assert [m.id for m in timeline.children(timeline.quarters[1])] == [
        "2026-04",
        "2026-05",
        "2026-06",
    ]
    assert timeline.children(timeline.full_year) == timeline.quarters
    assert timeline.children(timeline.months[0]) == ()


def test_full_year_spans_the_whole_year(timeline):
    year = timeline.full_year
    assert (year.id, year.label) == ("2026", "FY 2026")
    assert year.month_numbers == tuple(range(1, 13))
    assert len(timeline.periods) == 17


def test_unknown_period_is_refused(timeline):
    with pytest.raises(SpecError, match="unknown period"):
        timeline.period("2026-13")


def test_year_must_be_a_calendar_year():
    with pytest.raises(SpecError, match="calendar year"):
        Timeline(0)


def test_flows_sum_over_a_quarter_and_the_year(results):
    assert results.amount("2026-Q1", "receipts") == Decimal("600.00")
    assert results.amount("2026-Q1", "net_cash_flow") == Decimal("480.00")
    assert results.amount("2026", "receipts") == Decimal("7800.00")
    assert results.amount("2026", "net_cash_flow") == Decimal("7320.00")


def test_balances_take_the_edges_of_the_span(results):
    assert results.amount("2026", "opening_cash") == Decimal("1000.00")
    assert results.amount("2026", "closing_cash") == Decimal("8320.00")
    assert results.amount("2026", "closing_cash") == results.amount(
        "2026-12", "closing_cash"
    )
    assert results.amount("2026-Q2", "opening_cash") == results.amount(
        "2026-04", "opening_cash"
    )


def test_closing_balance_opens_the_next_period(results, timeline):
    for earlier, later in zip(timeline.months, timeline.months[1:]):
        assert results.amount(later, "opening_cash") == results.amount(
            earlier, "closing_cash"
        )


def test_first_opening_balance_comes_from_the_caller(results):
    assert results.amount("2026-01", "opening_cash") == Decimal("1000.00")
    assert results.amount("2026-01", "closing_cash") == Decimal("1060.00")


def test_opening_balance_defaults_to_zero(timeline):
    results = cash_model().run(timeline, monthly(timeline))
    assert results.amount("2026-01", "opening_cash") == Decimal("0.00")
    assert results.amount("2026", "closing_cash") == Decimal("7320.00")


def test_identity_is_proved_for_every_period(results, timeline):
    proofs = results.proofs()
    assert len(proofs) == len(timeline.periods)
    assert all(isinstance(proof, Proof) and proof.ok for proof in proofs)


def test_proof_reads_as_the_identity(results):
    assert (
        str(results.proofs("2026")[0])
        == "closing_cash over 2026: 1000.00 + 7320.00 = 8320.00 (holds)"
    )


def test_broken_identity_is_named(timeline):
    model = cash_model("opening_cash + net_cash_flow + 1")
    with pytest.raises(IdentityError) as error:
        model.run(timeline, monthly(timeline))
    assert error.value.proof.period.id == "2026-01"
    assert not error.value.proof.ok


def test_carried_opening_may_not_be_given(timeline):
    values = monthly(timeline)
    values["2026-03"]["opening_cash"] = Decimal("5")
    with pytest.raises(SpecError, match="carried between"):
        cash_model().run(timeline, values)


def test_every_month_must_have_values(timeline):
    values = monthly(timeline)
    del values["2026-07"]
    with pytest.raises(SpecError, match="2026-07"):
        cash_model().run(timeline, values)


def test_values_outside_the_timeline_are_refused(timeline):
    values = monthly(timeline)
    values["2027-01"] = {"receipts": Decimal("1"), "payments": Decimal("0")}
    with pytest.raises(SpecError, match="2027-01"):
        cash_model().run(timeline, values)


def test_unknown_opening_balance_is_refused(timeline):
    with pytest.raises(SpecError, match="carry none"):
        cash_model().run(timeline, monthly(timeline), opening={"receipts": Decimal("1")})


def test_carry_names_the_rollup_of_its_balances():
    model = cash_model()
    assert model.rollup_of("opening_cash") is Rollup.FIRST
    assert model.rollup_of("receipts") is Rollup.SUM


def test_stated_rollup_may_not_contradict_a_carry():
    with pytest.raises(SpecError, match="rolls up as 'first'"):
        PeriodicModel(
            cash_statement(),
            carries=[Carry(opening="opening_cash", closing="closing_cash")],
            rollups={"opening_cash": "last"},
        )


def test_unknown_rollup_is_refused():
    with pytest.raises(SpecError, match="unknown rollup"):
        PeriodicModel(cash_statement(), rollups={"receipts": "middle"})


def test_only_input_lines_roll_up():
    with pytest.raises(SpecError, match="is computed"):
        PeriodicModel(cash_statement(), rollups={"net_cash_flow": Rollup.LAST})


def test_carry_must_name_known_lines():
    with pytest.raises(SpecError, match="unknown line"):
        PeriodicModel(
            cash_statement(), carries=[Carry(opening="ghost", closing="closing_cash")]
        )


def test_stated_rollup_takes_the_last_value(timeline):
    statement = Statement(
        id="staff",
        label="Staff",
        children=[
            InputLine(id="headcount", label="Headcount"),
            ComputedLine(id="reported", label="Reported", formula="headcount"),
        ],
    )
    model = PeriodicModel(statement, rollups={"headcount": Rollup.LAST})
    values = {
        month.id: {"headcount": Decimal(number)}
        for number, month in enumerate(timeline.months, start=1)
    }
    results = model.run(timeline, values)
    assert results.amount("2026-Q1", "headcount") == Decimal("3")
    assert results.amount("2026", "reported") == Decimal("12")


def margin_model() -> PeriodicModel:
    return PeriodicModel(
        Statement(
            id="pnl",
            label="Profit and loss",
            rounding=Rounding(2),
            children=[
                InputLine(id="revenue", label="Revenue"),
                InputLine(id="cogs", label="Cost of goods sold"),
                ComputedLine(
                    id="gross_profit", label="Gross profit", formula="revenue - cogs"
                ),
                ComputedLine(
                    id="gross_margin",
                    label="Gross margin",
                    formula="gross_profit / revenue",
                    rounding=Rounding(4),
                ),
            ],
        )
    )


def test_ratios_are_recomputed_not_summed(timeline):
    values = {
        month.id: {
            "revenue": Decimal("0" if number == 1 else "100"),
            "cogs": Decimal("0" if number == 1 else "60"),
        }
        for number, month in enumerate(timeline.months, start=1)
    }
    results = margin_model().run(timeline, values)
    assert isinstance(results.amount("2026-01", "gross_margin"), NotApplicable)
    assert results.amount("2026-Q1", "gross_margin") == Decimal("0.4000")
    assert results.amount("2026", "revenue") == Decimal("1100.00")
    assert results.amount("2026", "gross_margin") == Decimal("0.4000")


def test_row_reads_one_line_across_the_timeline(results, timeline):
    row = results.row("closing_cash")
    assert list(row) == [period.id for period in timeline.periods]
    assert row["2026-01"] == Decimal("1060.00")


def test_frame_holds_every_line(results):
    assert set(results["2026-Q4"]) == {
        "opening_cash",
        "receipts",
        "payments",
        "net_cash_flow",
        "closing_cash",
    }


def test_unknown_line_and_period_are_refused(results):
    with pytest.raises(SpecError, match="unknown line"):
        results.amount("2026", "ghost")
    with pytest.raises(SpecError, match="unknown period"):
        results["2026-13"]
