# finmodel

Build financial statements from declarative table specs: P&L, cash flow and
balance sheet, with a safe formula evaluator instead of `eval()`.

## Status

Pre-alpha. Statements can be declared and validated; evaluation and rendering
are not implemented yet.

## Installation

```bash
pip install finmodel
```

## Declaring a statement

A statement is data: blocks group categories, input lines carry values and
computed lines derive them from a formula. Building a `Statement` validates the
whole tree — identifiers, duplicates, unknown references and reference cycles.

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

## Development

```bash
pip install -e .
```

## License

MIT

Built and maintained by [Shipmind Labs](https://shipmindlabs.com).
