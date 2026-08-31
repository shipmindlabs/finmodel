# finmodel

Build financial statements from declarative table specs: P&L, cash flow and
balance sheet, with a safe formula evaluator instead of `eval()`.

## Status

Pre-alpha. Statements can be declared and validated, formulas parse and
evaluate, and a single period can be computed with per-line rounding; multiple
periods and rendering are not implemented yet.

## Installation

```bash
pip install finmodel
```

## Declaring a statement

A statement is data: blocks group categories, input lines carry values and
computed lines derive them from a formula. Building a `Statement` validates the
whole tree — identifiers, duplicates, formula syntax, unknown references and
reference cycles.

```python
from finmodel import Block, ComputedLine, InputLine, Statement

pnl = Statement(
    id="pnl",
    label="Profit and loss",
    children=[
        Block(
            id="revenue",
            label="Revenue",
            children=[
                InputLine(id="product_sales", label="Product sales"),
                InputLine(id="services", label="Services"),
                ComputedLine(
                    id="total_revenue",
                    label="Total revenue",
                    formula="product_sales + services",
                ),
            ],
        ),
        Block(
            id="costs",
            label="Costs",
            children=[InputLine(id="cogs", label="Cost of goods sold")],
        ),
        ComputedLine(
            id="gross_profit",
            label="Gross profit",
            formula="total_revenue - cogs",
        ),
    ],
)

pnl.evaluation_order
# ('total_revenue', 'gross_profit')

for node, depth in pnl.walk():
    print("  " * depth + node.label)
```

## Evaluation order

`evaluation_order` is a topological sort of the computed lines over the graph of
their references, so a line always comes after everything it reads, whatever
order the spec declares. `dependency_graph` exposes the same edges, keyed by
line id. The sort keeps its own stack, so a deep chain of lines is ordered
instead of hitting the recursion limit.

A cycle is a `CircularReferenceError` — a named error carrying the path that
closes the loop, not a stack overflow three layers down.

```python
from finmodel import CircularReferenceError, ComputedLine, InputLine, Statement

try:
    Statement(
        id="broken",
        label="Broken",
        children=[
            ComputedLine(id="ebit", label="EBIT", formula="ebitda - depreciation"),
            ComputedLine(id="ebitda", label="EBITDA", formula="ebit + depreciation"),
            InputLine(id="depreciation", label="Depreciation"),
        ],
    )
except CircularReferenceError as error:
    print(error)
    # circular reference: ebit -> ebitda -> ebit
    error.cycle
    # ('ebit', 'ebitda', 'ebit')
```

`CircularReferenceError` is a `SpecError`, so callers that only care about an
invalid spec can keep catching the base class.

## Formulas

Formulas are never handed to `eval()`. A formula is tokenised and parsed into a
small expression tree — line references, decimal literals, `+ - * /`, a unary
sign and parentheses — and then evaluated over an explicit scope. Anything
outside that grammar (calls, attribute access, comparisons) is a parse error,
and a name that the scope does not bind is an evaluation error.

```python
from decimal import Decimal
from finmodel import evaluate, parse

expression = parse("(product_sales + services) * 0.9 - cogs")
expression.references
# ('product_sales', 'services', 'cogs')

expression.evaluate(
    {
        "product_sales": Decimal("1200"),
        "services": Decimal("300"),
        "cogs": Decimal("450"),
    }
)
# Decimal('900.0')
```

Every `ComputedLine` exposes its parsed tree as `line.expression`, so a
statement is parsed once at construction and evaluated many times.

## Money, rounding and division by zero

Amounts are `Decimal` end to end. Integers, floats and strings handed in through
a scope are converted exactly — a float through its shortest repr — so nothing
reaches the arithmetic as binary floating point.

Rounding is stated, never implicit. A `Rounding` carries a number of decimal
places and a mode, defaulting to `ROUND_HALF_UP` rather than the banker's
rounding of the `decimal` module. Lines state their own; a statement may state
a default for the lines that do not. Negative digits round to units of ten.

A division by zero is an answer, not a crash: it yields `NotApplicable`, which
carries the reason and propagates through every line that reads it, so a period
with no revenue reports margins as not applicable instead of raising three
levels down.

```python
from decimal import Decimal
from finmodel import Block, ComputedLine, InputLine, Rounding, Statement, evaluate

evaluate("gross_profit / total_revenue", {"gross_profit": Decimal("90"), "total_revenue": Decimal("0")})
# NotApplicable(reason='division by zero')

pnl = Statement(
    id="pnl",
    label="Profit and loss",
    rounding=Rounding(2),
    children=[
        Block(
            id="revenue",
            label="Revenue",
            children=[InputLine(id="total_revenue", label="Total revenue")],
        ),
        InputLine(id="cogs", label="Cost of goods sold"),
        ComputedLine(
            id="gross_profit",
            label="Gross profit",
            formula="total_revenue - cogs",
        ),
        ComputedLine(
            id="gross_margin",
            label="Gross margin",
            formula="gross_profit / total_revenue",
            rounding=Rounding(4),
        ),
    ],
)

pnl.evaluate({"total_revenue": Decimal("1500"), "cogs": Decimal("449.995")})
# {'total_revenue': Decimal('1500.00'),
#  'cogs': Decimal('450.00'),
#  'gross_profit': Decimal('1050.00'),
#  'gross_margin': Decimal('0.7000')}

result = pnl.evaluate({"total_revenue": Decimal("0"), "cogs": Decimal("120")})
print(result["gross_margin"])
# n/a (division by zero)
```

`evaluate` computes one period in dependency order and returns every line in
declaration order. Missing or unexpected input values are a `SpecError`, so a
period is either complete or refused.

## Development

```bash
pip install -e .
```

## License

MIT

Built and maintained by [Shipmind Labs](https://shipmindlabs.com).
