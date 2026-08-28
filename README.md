# finmodel

Build financial statements from declarative table specs: P&L, cash flow and
balance sheet, with a safe formula evaluator instead of `eval()`.

## Status

Pre-alpha. Statements can be declared and validated and formulas parse and
evaluate; period values and rendering are not implemented yet.

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
and a name that the scope does not bind is an evaluation error. Arithmetic uses
`Decimal`, so amounts keep their scale.

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

evaluate("margin / periods", {"margin": Decimal("90"), "periods": Decimal("0")})
# FormulaError: division by zero
```

Every `ComputedLine` exposes its parsed tree as `line.expression`, so a
statement is parsed once at construction and evaluated many times.

## Development

```bash
pip install -e .
```

## License

MIT

Built and maintained by [Shipmind Labs](https://shipmindlabs.com).
