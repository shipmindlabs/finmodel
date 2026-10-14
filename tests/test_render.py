"""Rendering: one table from a spec, the same rows as Markdown and as CSV."""

import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

from finmodel import (
    Block,
    ComputedLine,
    InputLine,
    Rounding,
    SpecError,
    Statement,
    Timeline,
    render_csv,
    render_markdown,
    tabulate,
)
from finmodel.render import BLOCK, COMPUTED, INPUT

GOLDEN = Path(__file__).parent / "golden"


def load(name: str) -> dict:
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def given(values: dict) -> dict:
    return {line: Decimal(amount) for line, amount in values.items()}


PNL = load("saas_pnl")
CASH = load("cash_flow_2026")
SHEET = load("balance_sheet_2026")


def run_cash(model):
    timeline = Timeline(CASH["year"])
    months = {month: given(values) for month, values in CASH["months"].items()}
    return timeline, model.run(timeline, months, opening=given(CASH["opening"]))


def unit_economics() -> Statement:
    return Statement(
        id="metrics",
        label="Unit economics",
        rounding=Rounding(2),
        children=[
            Block(
                id="volume",
                label="Volume",
                children=[
                    InputLine(
                        id="customers",
                        label="Customers",
                        unit="count",
                        rounding=Rounding(0),
                    ),
                    InputLine(id="revenue", label="Revenue", unit="USD"),
                ],
            ),
            ComputedLine(
                id="arpu",
                label="Revenue per customer",
                formula="revenue / customers",
            ),
        ],
    )


PNL_CSV = """\
id,label,depth,unit,Amount
revenue,Revenue,0,,
subscriptions,Subscriptions,1,,800000.00
services,Professional services,1,,200000.00
total_revenue,Total revenue,1,,1000000.00
cost_of_revenue,Cost of revenue,0,,
hosting,Hosting,1,,150000.00
support,Customer support,1,,50000.00
total_cost_of_revenue,Total cost of revenue,1,,200000.00
gross_profit,Gross profit,0,,800000.00
gross_margin,Gross margin,0,,0.8000
operating_expenses,Operating expenses,0,,
sales_and_marketing,Sales and marketing,1,,300000.00
research_and_development,Research and development,1,,250000.00
general_and_administrative,General and administrative,1,,150000.00
total_operating_expenses,Total operating expenses,1,,700000.00
operating_income,Operating income,0,,100000.00
operating_margin,Operating margin,0,,0.1000
"""

CASH_MARKDOWN = """\
| Cash flow                       | 2026-01 |    2026 |
| :------------------------------ | ------: | ------: |
| Opening cash                    |  500.00 |  500.00 |
| Receipts from customers         |  100.00 | 7800.00 |
| Payments to suppliers and staff |   60.00 |  720.00 |
| Net cash flow                   |   40.00 | 7080.00 |
| Closing cash                    |  540.00 | 7580.00 |
"""

UNIT_CSV = """\
id,label,depth,unit,2026-01,2026-02
volume,Volume,0,,,
customers,Customers,1,count,0,4
revenue,Revenue,1,USD,0.00,1000.00
arpu,Revenue per customer,0,,n/a (division by zero),250.00
"""


def test_rows_follow_the_spec_with_blocks_at_their_depth(balance_sheet_statement):
    amounts = balance_sheet_statement.evaluate(given(SHEET["inputs"]))
    table = tabulate(balance_sheet_statement, amounts)
    assert [(row.id, row.depth, row.kind) for row in table.rows] == [
        ("current_assets", 0, BLOCK),
        ("cash", 1, INPUT),
        ("receivables", 1, INPUT),
        ("inventory", 1, INPUT),
        ("total_current_assets", 1, COMPUTED),
        ("fixed_assets", 0, BLOCK),
        ("equipment", 1, INPUT),
        ("accumulated_depreciation", 1, INPUT),
        ("net_fixed_assets", 1, COMPUTED),
        ("total_assets", 0, COMPUTED),
        ("liabilities", 0, BLOCK),
        ("payables", 1, INPUT),
        ("deferred_revenue", 1, INPUT),
        ("total_liabilities", 1, COMPUTED),
        ("equity", 0, BLOCK),
        ("share_capital", 1, INPUT),
        ("retained_earnings", 1, INPUT),
        ("total_equity", 1, COMPUTED),
        ("total_liabilities_and_equity", 0, COMPUTED),
    ]
    assert table.row("accumulated_depreciation").cells == ("-800.00",)


def test_a_block_is_a_header_with_empty_cells(balance_sheet_statement):
    amounts = balance_sheet_statement.evaluate(given(SHEET["inputs"]))
    header = tabulate(balance_sheet_statement, amounts).row("liabilities")
    assert header.is_header
    assert header.amounts == (None,)
    assert header.cells == ("",)


def test_one_period_of_amounts_is_a_single_column(pnl_statement):
    amounts = pnl_statement.evaluate(given(PNL["cases"][0]["inputs"]))
    table = tabulate(pnl_statement, amounts)
    assert table.label == "Profit and loss"
    assert table.columns == ("Amount",)
    assert table.amount("gross_margin", "Amount") == Decimal("0.8000")


def test_the_profit_and_loss_renders_to_fixed_csv(pnl_statement):
    amounts = pnl_statement.evaluate(given(PNL["cases"][0]["inputs"]))
    assert render_csv(tabulate(pnl_statement, amounts)) == PNL_CSV


def test_the_cash_flow_renders_to_fixed_markdown(cash_flow_model):
    _, results = run_cash(cash_flow_model)
    table = tabulate(
        cash_flow_model.statement,
        {"2026-01": results["2026-01"], "2026": results["2026"]},
    )
    assert render_markdown(table) == CASH_MARKDOWN


def test_a_whole_timeline_is_one_column_per_period(cash_flow_model):
    timeline, results = run_cash(cash_flow_model)
    table = tabulate(cash_flow_model.statement, results)
    assert table.columns == tuple(period.id for period in timeline.periods)
    assert table.amount("closing_cash", "2026-07") == Decimal("2880.00")
    assert render_markdown(table).count("\n") == len(table.rows) + 2


def test_a_period_names_its_own_column(cash_flow_model):
    timeline, results = run_cash(cash_flow_model)
    table = tabulate(cash_flow_model.statement, {timeline.full_year: results["2026"]})
    assert table.columns == ("2026",)


def test_the_csv_parses_back_to_the_rows_it_was_written_from(cash_flow_model):
    _, results = run_cash(cash_flow_model)
    table = tabulate(cash_flow_model.statement, results)
    parsed = list(csv.reader(io.StringIO(render_csv(table))))
    assert parsed[0] == ["id", "label", "depth", "unit", *table.columns]
    assert len(parsed) == len(table.rows) + 1
    assert parsed[1][:5] == ["opening_cash", "Opening cash", "0", "", "500.00"]


def test_units_and_non_answers_print_in_both_writers():
    statement = unit_economics()
    table = tabulate(
        statement,
        {
            "2026-01": statement.evaluate(
                {"customers": Decimal(0), "revenue": Decimal(0)}
            ),
            "2026-02": statement.evaluate(
                {"customers": Decimal(4), "revenue": Decimal(1000)}
            ),
        },
    )
    assert render_csv(table) == UNIT_CSV
    lines = render_markdown(table).splitlines()
    assert table.row("customers").title == "Customers (count)"
    assert "**Volume**" in lines[2]
    assert "  Customers (count)" in lines[3]
    assert lines[-1] == "| Revenue per customer | n/a (division by zero) |  250.00 |"


def test_a_pipe_in_a_label_does_not_break_the_row():
    statement = Statement(
        id="odd",
        label="Odd | labels",
        children=[InputLine(id="a", label="A | B")],
    )
    markdown = render_markdown(tabulate(statement, {"a": Decimal(1)}))
    assert markdown.splitlines()[0].startswith("| Odd \\| labels")
    assert "| A \\| B" in markdown


def test_a_column_missing_a_line_is_refused(pnl_statement):
    amounts = pnl_statement.evaluate(given(PNL["cases"][0]["inputs"]))
    del amounts["gross_margin"]
    with pytest.raises(SpecError, match="no amount for line 'gross_margin'"):
        tabulate(pnl_statement, amounts)


def test_columns_must_all_be_periods_or_all_be_amounts(pnl_statement):
    with pytest.raises(SpecError, match="either all be periods"):
        tabulate(
            pnl_statement,
            {"gross_profit": Decimal(1), "2026-01": {"gross_profit": Decimal(1)}},
        )


def test_only_results_or_a_mapping_can_be_tabulated(pnl_statement):
    with pytest.raises(SpecError, match="cannot tabulate list"):
        tabulate(pnl_statement, [("gross_profit", Decimal(1))])


def test_unknown_rows_and_columns_are_refused(pnl_statement):
    amounts = pnl_statement.evaluate(given(PNL["cases"][0]["inputs"]))
    table = tabulate(pnl_statement, amounts)
    with pytest.raises(SpecError, match="unknown row 'ghost'"):
        table.row("ghost")
    with pytest.raises(SpecError, match="unknown column '2027'"):
        table.amount("gross_profit", "2027")
