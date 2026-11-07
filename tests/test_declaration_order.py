"""Declaration order is presentation: shuffling a spec may not move a number."""

import random
from decimal import Decimal

import pytest

from finmodel import (
    Block,
    CircularReferenceError,
    ComputedLine,
    InputLine,
    Node,
    NotApplicable,
    Rounding,
    Statement,
)

SEEDS = tuple(range(1, 41))

INPUTS = {
    "subscriptions": Decimal("800000"),
    "services": Decimal("200000"),
    "grants": Decimal("5000"),
    "interest_income": Decimal("1000"),
    "hosting": Decimal("150000"),
    "salaries": Decimal("250000"),
}

NO_REVENUE = {
    "subscriptions": Decimal(0),
    "services": Decimal(0),
    "grants": Decimal(0),
    "interest_income": Decimal(0),
    "hosting": Decimal("1200.555"),
    "salaries": Decimal("800"),
}

PERIODS = (INPUTS, NO_REVENUE)

CYCLE = {"ebit", "ebitda", "interest"}


def pnl() -> Statement:
    """A statement whose lines read across blocks and nested blocks."""
    return Statement(
        id="pnl",
        label="Profit and loss",
        rounding=Rounding(2),
        children=[
            Block(
                id="revenue",
                label="Revenue",
                children=[
                    InputLine(id="subscriptions", label="Subscriptions", unit="USD"),
                    InputLine(id="services", label="Professional services"),
                    Block(
                        id="other_revenue",
                        label="Other revenue",
                        children=[
                            InputLine(id="grants", label="Grants"),
                            InputLine(id="interest_income", label="Interest income"),
                            ComputedLine(
                                id="total_other_revenue",
                                label="Total other revenue",
                                formula="grants + interest_income",
                            ),
                        ],
                    ),
                    ComputedLine(
                        id="total_revenue",
                        label="Total revenue",
                        formula="subscriptions + services + total_other_revenue",
                    ),
                ],
            ),
            Block(
                id="costs",
                label="Costs",
                children=[
                    InputLine(id="hosting", label="Hosting"),
                    InputLine(id="salaries", label="Salaries"),
                    ComputedLine(
                        id="total_costs",
                        label="Total costs",
                        formula="hosting + salaries",
                    ),
                ],
            ),
            ComputedLine(
                id="gross_profit",
                label="Gross profit",
                formula="total_revenue - total_costs",
            ),
            ComputedLine(
                id="gross_margin",
                label="Gross margin",
                formula="gross_profit / total_revenue",
                rounding=Rounding(4),
            ),
            ComputedLine(id="tax", label="Tax", formula="max(gross_profit, 0) * 0.25"),
            ComputedLine(
                id="net_income", label="Net income", formula="gross_profit - tax"
            ),
        ],
    )


def looped_children() -> list[Node]:
    """Children of a statement three of whose lines depend on one another."""
    return [
        Block(
            id="operating",
            label="Operating",
            children=[
                InputLine(id="depreciation", label="Depreciation"),
                ComputedLine(
                    id="ebitda", label="EBITDA", formula="interest + depreciation"
                ),
            ],
        ),
        ComputedLine(id="ebit", label="EBIT", formula="ebitda - depreciation"),
        ComputedLine(id="interest", label="Interest", formula="ebit * 0.1"),
        InputLine(id="revenue", label="Revenue"),
        ComputedLine(id="reported", label="Reported EBIT", formula="ebit + revenue"),
    ]


def shuffle(nodes: list[Node], rng: random.Random) -> list[Node]:
    """The same nodes, siblings in another order, blocks keeping their children."""
    reordered = [_reshape(node, rng) for node in nodes]
    rng.shuffle(reordered)
    return reordered


def _reshape(node: Node, rng: random.Random) -> Node:
    if isinstance(node, Block):
        return Block(
            id=node.id,
            label=node.label,
            children=shuffle(list(node.children), rng),
        )
    return node


def reshuffled(statement: Statement, seed: int) -> Statement:
    rng = random.Random(seed)
    return Statement(
        id=statement.id,
        label=statement.label,
        rounding=statement.rounding,
        children=shuffle(list(statement.children), rng),
    )


def layout(statement: Statement) -> tuple[tuple[str, int], ...]:
    return tuple((node.id, depth) for node, depth in statement.walk())


def declared(statement: Statement) -> list[str]:
    return [node.id for node, _ in statement.walk() if not isinstance(node, Block)]


def test_the_seeds_really_do_reorder_the_spec():
    layouts = {layout(reshuffled(pnl(), seed)) for seed in SEEDS}
    assert len(layouts) > len(SEEDS) // 2


def test_shuffling_moves_siblings_without_reparenting_them():
    depths = {node.id: depth for node, depth in pnl().walk()}
    for seed in SEEDS:
        shuffled = reshuffled(pnl(), seed)
        assert {node.id: depth for node, depth in shuffled.walk()} == depths


def test_the_period_without_revenue_really_is_a_non_answer():
    amounts = pnl().evaluate(NO_REVENUE)
    assert isinstance(amounts["gross_margin"], NotApplicable)
    assert amounts["total_revenue"] == Decimal("0.00")


@pytest.mark.parametrize("seed", SEEDS)
def test_the_same_amounts_whatever_the_order(seed):
    base = pnl()
    shuffled = reshuffled(base, seed)
    for values in PERIODS:
        expected = base.evaluate(values)
        amounts = shuffled.evaluate(values)
        assert amounts == expected
        assert {line: str(amount) for line, amount in amounts.items()} == {
            line: str(amount) for line, amount in expected.items()
        }


@pytest.mark.parametrize("seed", SEEDS)
def test_the_same_edges_whatever_the_order(seed):
    base = pnl()
    shuffled = reshuffled(base, seed)
    assert shuffled.dependency_graph == base.dependency_graph
    assert set(declared(shuffled)) == set(declared(base))


@pytest.mark.parametrize("seed", SEEDS)
def test_evaluation_order_stays_a_topological_order(seed):
    shuffled = reshuffled(pnl(), seed)
    graph = shuffled.dependency_graph
    computed = {line.id for line in shuffled.computed_lines}
    order = shuffled.evaluation_order
    assert len(order) == len(computed)
    assert set(order) == computed
    placed: set[str] = set()
    for line_id in order:
        for reference in graph[line_id]:
            assert reference not in computed or reference in placed, (line_id, reference)
        placed.add(line_id)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_amounts_are_listed_in_the_order_the_spec_declares(seed):
    shuffled = reshuffled(pnl(), seed)
    assert list(shuffled.evaluate(INPUTS)) == declared(shuffled)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_cycle_names_the_same_lines_whatever_the_order(seed):
    children = shuffle(looped_children(), random.Random(seed))
    with pytest.raises(CircularReferenceError) as error:
        Statement(id="broken", label="Broken", children=children)
    cycle = error.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == CYCLE
    assert len(cycle) == len(CYCLE) + 1
    assert str(error.value).startswith("circular reference: ")
