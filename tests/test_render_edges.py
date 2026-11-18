"""Rendering edges: a table built by hand, odd labels, and tables that are refused."""

import csv
import io
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from finmodel import (
    NA,
    Block,
    FormulaError,
    InputLine,
    Rounding,
    Row,
    SpecError,
    Statement,
    Table,
    Timeline,
    render_csv,
    render_markdown,
    tabulate,
)
from finmodel.render import AMOUNT_COLUMN, BLOCK, INPUT


def statement(
    *lines: InputLine, label: str = "S", rounding: Rounding | None = None
) -> Statement:
    return Statement(id="s", label=label, children=list(lines), rounding=rounding)


def test_a_table_with_no_rows_is_a_header_and_a_rule():
    table = Table(label="Nothing")
    assert (table.columns, table.rows) == ((), ())
    assert render_markdown(table) == "| Nothing |\n| :------ |\n"
    assert render_csv(table) == "id,label,depth,unit\n"


def test_the_writers_need_nothing_but_a_table():
    table = Table(
        label="By hand",
        columns=["Q1"],
        rows=[
            Row(id="g", label="Group", depth=0, kind=BLOCK, amounts=(None,)),
            Row(
                id="x",
                label="X",
                depth=1,
                kind=INPUT,
                unit="USD",
                amounts=(Decimal("1.50"),),
            ),
        ],
    )
    assert table.columns == ("Q1",)
    assert table.amount("g", "Q1") is None
    assert table.amount("x", "Q1") == Decimal("1.50")
    assert render_markdown(table) == (
        "| By hand   |   Q1 |\n"
        "| :-------- | ---: |\n"
        "| **Group** |      |\n"
        "|   X (USD) | 1.50 |\n"
    )
    assert render_csv(table) == (
        "id,label,depth,unit,Q1\ng,Group,0,,\nx,X,1,USD,1.50\n"
    )


def test_a_narrow_column_is_still_three_wide():
    table = Table(
        label="P",
        columns=("Q",),
        rows=[Row(id="a", label="A", depth=0, kind=INPUT, amounts=(Decimal(1),))],
    )
    assert render_markdown(table) == "| P   |   Q |\n| :-- | --: |\n| A   |   1 |\n"


def test_a_header_shows_nothing_and_a_line_shows_its_non_answer():
    table = Table(
        label="S",
        columns=("Q1", "Q2"),
        rows=[
            Row(id="g", label="Group", depth=0, kind=BLOCK, amounts=(None, None)),
            Row(id="a", label="A", depth=0, kind=INPUT, amounts=(NA, Decimal("2.00"))),
        ],
    )
    assert table.row("g").is_header
    assert table.row("g").cells == ("", "")
    assert table.row("a").cells == (str(NA), "2.00")
    assert str(NA) in render_markdown(table)
    assert str(NA) in render_csv(table)


def test_a_pipe_in_a_column_or_a_unit_is_escaped_only_in_markdown():
    table = tabulate(
        statement(InputLine(id="a", label="A", unit="EUR|USD")),
        {"a|b": {"a": Decimal(1)}},
    )
    assert table.columns == ("a|b",)
    markdown = render_markdown(table).splitlines()
    assert "a\\|b" in markdown[0]
    assert "A (EUR\\|USD)" in markdown[2]
    assert render_csv(table).splitlines() == [
        "id,label,depth,unit,a|b",
        "a,A,0,EUR|USD,1",
    ]


def test_a_unit_that_is_empty_is_not_shown():
    table = tabulate(statement(InputLine(id="a", label="A", unit="")), {"a": Decimal(1)})
    assert table.row("a").title == "A"
    assert render_csv(table).splitlines()[1] == "a,A,0,,1"


def test_a_mapping_with_nothing_in_it_is_a_column_without_amounts():
    with pytest.raises(SpecError, match="no amount for line 'a' in column 'Amount'"):
        tabulate(statement(InputLine(id="a", label="A")), {})


def test_the_column_missing_an_amount_is_the_one_named():
    spec = statement(InputLine(id="a", label="A"), InputLine(id="b", label="B"))
    with pytest.raises(SpecError, match="no amount for line 'b' in column '2026-02'"):
        tabulate(spec, {"2026-01": {"a": 1, "b": 2}, "2026-02": {"a": 3}})


def test_cells_convert_what_they_are_given_exactly():
    spec = statement(
        InputLine(id="a", label="A"),
        InputLine(id="b", label="B"),
        InputLine(id="c", label="C"),
    )
    table = tabulate(spec, {"a": 1, "b": "2.50", "c": 0.1})
    assert table.columns == (AMOUNT_COLUMN,)
    assert [row.cells for row in table.rows] == [("1",), ("2.50",), ("0.1",)]


def test_a_value_that_is_not_finite_is_refused_by_its_line():
    spec = statement(InputLine(id="a", label="A"))
    for value in (float("nan"), float("inf"), Decimal("NaN"), "-Infinity"):
        with pytest.raises(FormulaError, match="'a' is not a finite number"):
            tabulate(spec, {"a": value})


def test_a_table_shows_the_amounts_it_is_given_not_the_scale_of_the_spec():
    spec = statement(InputLine(id="a", label="A"), rounding=Rounding(2))
    assert tabulate(spec, {"a": Decimal("1.5")}).row("a").cells == ("1.5",)
    assert tabulate(spec, spec.evaluate({"a": Decimal("1.5")})).row("a").cells == (
        "1.50",
    )


def test_nested_blocks_indent_two_spaces_a_level():
    spec = Statement(
        id="deep",
        label="Deep",
        children=[
            Block(
                id="one",
                label="One",
                children=[
                    Block(
                        id="two",
                        label="Two",
                        children=[
                            Block(
                                id="three",
                                label="Three",
                                children=[InputLine(id="a", label="A")],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    table = tabulate(spec, {"a": Decimal(5)})
    assert [(row.id, row.depth) for row in table.rows] == [
        ("one", 0),
        ("two", 1),
        ("three", 2),
        ("a", 3),
    ]
    lines = render_markdown(table).splitlines()
    assert lines[2].startswith("| **One**")
    assert lines[3].startswith("|   **Two**")
    assert lines[4].startswith("|     **Three**")
    assert lines[5].startswith("|       A")
    parsed = list(csv.reader(io.StringIO(render_csv(table))))
    assert parsed[4] == ["a", "A", "3", "", "5"]


def test_csv_quotes_a_label_that_carries_its_own_comma():
    text = render_csv(
        tabulate(statement(InputLine(id="a", label='A, "B"')), {"a": Decimal(1)})
    )
    assert text.splitlines()[1] == 'a,"A, ""B""",0,,1'
    assert list(csv.reader(io.StringIO(text)))[1] == ["a", 'A, "B"', "0", "", "1"]


def test_a_results_without_the_lines_of_the_statement_is_refused(
    cash_flow_model, balance_sheet_statement
):
    timeline = Timeline(2026)
    months = {
        month.id: {"receipts": Decimal(10), "payments": Decimal(4)}
        for month in timeline.months
    }
    results = cash_flow_model.run(timeline, months)
    with pytest.raises(
        SpecError, match="no amount for line 'cash' in column '2026-01'"
    ):
        tabulate(balance_sheet_statement, results)


def test_a_table_is_frozen_and_equal_to_the_same_table():
    spec = statement(InputLine(id="a", label="A"))
    table = tabulate(spec, {"a": Decimal(1)})
    with pytest.raises(FrozenInstanceError):
        table.label = "Other"
    with pytest.raises(FrozenInstanceError):
        table.rows[0].label = "Other"
    assert tabulate(spec, {"a": Decimal(1)}) == table
