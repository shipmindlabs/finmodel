"""Calls: three functions in a closed table, checked where the formula is parsed."""

from decimal import Decimal

import pytest

from finmodel import (
    FUNCTIONS,
    NA,
    Block,
    Call,
    ComputedLine,
    FormulaError,
    InputLine,
    Number,
    Reference,
    Rounding,
    SpecError,
    Statement,
    evaluate,
    parse,
)
from finmodel.formula import MAX_DEPTH


def taxed() -> Statement:
    return Statement(
        id="pnl",
        label="Profit and loss",
        rounding=Rounding(2),
        children=[
            Block(
                id="trading",
                label="Trading",
                children=[InputLine(id="revenue", label="Revenue")],
            ),
            InputLine(id="costs", label="Costs"),
            ComputedLine(id="profit", label="Profit", formula="revenue - costs"),
            ComputedLine(id="tax", label="Tax", formula="max(profit, 0) * 0.25"),
            ComputedLine(id="drawdown", label="Drawdown", formula="abs(min(profit, 0))"),
        ],
    )


def test_the_table_holds_three_functions_and_nothing_else():
    assert set(FUNCTIONS) == {"abs", "max", "min"}
    assert FUNCTIONS["abs"].arity == "exactly 1 argument"
    assert FUNCTIONS["min"].arity == "at least 2 arguments"
    with pytest.raises(TypeError):
        FUNCTIONS["sum"] = FUNCTIONS["min"]


def test_each_function_computes_what_it_names():
    scope = {"a": Decimal("-12.5"), "b": Decimal(4), "c": Decimal("0.5")}
    assert evaluate("abs(a)", scope) == Decimal("12.5")
    assert evaluate("abs(b)", scope) == Decimal(4)
    assert evaluate("min(a, b, c)", scope) == Decimal("-12.5")
    assert evaluate("max(a, b, c)", scope) == Decimal(4)
    assert evaluate("min(b, c)", scope) == Decimal("0.5")


def test_a_call_is_an_atom_of_the_grammar():
    scope = {"revenue": Decimal(100), "cogs": Decimal(140)}
    assert evaluate("max(revenue - cogs, 0) * 2", scope) == Decimal(0)
    assert evaluate("-abs(revenue - cogs)", scope) == Decimal(-40)
    assert evaluate("abs(min(revenue, cogs) - 200)", scope) == Decimal(100)
    assert evaluate("(abs(revenue) + 1) / 2", scope) == Decimal("50.5")


def test_the_tree_is_a_call_node_with_its_arguments():
    assert parse("min(revenue, 0)") == Call(
        "min", (Reference("revenue"), Number(Decimal(0)))
    )
    assert parse("abs(revenue)").name == "abs"
    assert len(parse("max(a, b, c)").arguments) == 3


def test_references_come_from_the_arguments_in_order():
    assert parse("max(cogs, revenue, cogs)").references == ("cogs", "revenue")
    assert parse("abs(a - b) + min(b, c)").references == ("a", "b", "c")
    assert parse("min(1, 2)").references == ()


def test_a_function_name_is_never_a_line_reference():
    for text in ("min", "min + 1", "1 + max", "abs * 2"):
        with pytest.raises(FormulaError, match="is not a line reference"):
            parse(text)
    assert parse("minimum + maxed").references == ("minimum", "maxed")


def test_a_non_answer_is_the_answer_of_the_call():
    assert evaluate("abs(1 / 0)", {}) == NA
    assert evaluate("min(1, 1 / 0)", {}) == NA
    assert evaluate("max(1 / 0, 1) + 3", {}) == NA
    assert evaluate("abs(revenue / cogs)", {"revenue": 1, "cogs": 0}) == NA


def test_arguments_stop_at_the_first_non_answer():
    assert evaluate("min(1 / 0, ghost)", {}) == NA
    with pytest.raises(FormulaError, match="unbound reference 'ghost'"):
        evaluate("min(ghost, 1 / 0)", {})


def test_the_wrong_number_of_arguments_is_refused_at_its_position():
    with pytest.raises(
        FormulaError, match="min takes at least 2 arguments, got 1 at position 0"
    ):
        parse("min(revenue)")
    with pytest.raises(
        FormulaError, match="abs takes exactly 1 argument, got 2 at position 4"
    ):
        parse("1 + abs(a, b)")
    with pytest.raises(FormulaError, match="abs takes exactly 1 argument, got 0"):
        parse("abs()")
    with pytest.raises(FormulaError, match="max takes at least 2 arguments, got 0"):
        parse("max()")


def test_an_unknown_name_called_is_a_formula_error_at_its_position():
    with pytest.raises(FormulaError, match="unknown function 'total' at position 0"):
        parse("total(a, b)")
    with pytest.raises(FormulaError, match="unknown function 'sum' at position 10"):
        parse("revenue + sum(a, b)")
    with pytest.raises(FormulaError, match="unknown function 'ABS' at position 0"):
        parse("ABS(a)")


def test_a_call_must_close_and_separate_its_arguments():
    with pytest.raises(FormulaError, match=r"expected '\)' at position 8"):
        parse("min(a, b")
    with pytest.raises(FormulaError, match=r"unexpected '\)' at position 7"):
        parse("min(a, )")
    with pytest.raises(FormulaError, match="unexpected ',' at position 1"):
        parse("a, b")


def test_calls_nest_up_to_the_bound():
    nested = "abs(" * MAX_DEPTH + "1" + ")" * MAX_DEPTH
    assert evaluate(nested, {}) == Decimal(1)
    deeper = "abs(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1)
    with pytest.raises(FormulaError, match="nests deeper than"):
        parse(deeper)


def test_a_call_node_checks_itself_when_it_is_built():
    with pytest.raises(FormulaError, match="unknown function 'total'"):
        Call("total", (Number(Decimal(1)),))
    with pytest.raises(FormulaError, match="min takes at least 2 arguments, got 1"):
        Call("min", (Number(Decimal(1)),))
    call = Call("max", [Number(Decimal(1)), Number(Decimal(2))])
    assert call.arguments == (Number(Decimal(1)), Number(Decimal(2)))
    assert call.evaluate({}) == Decimal(2)


def test_a_statement_computes_with_calls_in_its_formulas():
    statement = taxed()
    assert statement.line("tax").references == ("profit",)
    assert statement.evaluation_order == ("profit", "tax", "drawdown")
    good = statement.evaluate({"revenue": Decimal(1000), "costs": Decimal(600)})
    assert good["tax"] == Decimal("100.00")
    assert good["drawdown"] == Decimal("0.00")
    bad = statement.evaluate({"revenue": Decimal(100), "costs": Decimal(600)})
    assert bad["tax"] == Decimal("0.00")
    assert bad["drawdown"] == Decimal("500.00")


def test_an_id_may_not_be_a_function_name():
    for name in ("min", "max", "abs"):
        with pytest.raises(SpecError, match=f"id '{name}' is a function name"):
            InputLine(id=name, label="Shadow")
    with pytest.raises(SpecError, match="block id 'min' is a function name"):
        Block(id="min", label="Shadow", children=[InputLine(id="a", label="A")])


def test_a_call_in_a_line_still_resolves_its_references():
    with pytest.raises(SpecError, match="references unknown line 'ghost'"):
        Statement(
            id="s",
            label="S",
            children=[
                InputLine(id="revenue", label="Revenue"),
                ComputedLine(id="floor", label="Floor", formula="max(revenue, ghost)"),
            ],
        )


def test_a_malformed_call_in_a_line_is_a_spec_error():
    with pytest.raises(SpecError, match="formula of 'floor' is invalid: min takes"):
        ComputedLine(id="floor", label="Floor", formula="min(revenue)")
