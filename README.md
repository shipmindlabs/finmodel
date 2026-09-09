# finmodel

Build financial statements from declarative table specs: P&L, cash flow and
balance sheet, with a safe formula evaluator instead of `eval()`.

## Status

Pre-alpha. Statements can be declared and validated, formulas parse and
evaluate, a single period computes with per-line rounding, twelve months roll
into quarters and a year with balances carried across the boundaries, and
checks state what the numbers must agree on; rendering is not implemented yet.

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

## Twelve months make a year

A `Timeline` is one calendar year: twelve months, the four quarters over them
and the year itself. A `PeriodicModel` pairs a statement with the balances that
survive a period boundary, computes every month in order and rolls the longer
spans up from the shorter ones.

A flow sums over a span, a balance takes an edge of it: `Carry` names the
opening line, the closing line that feeds the next period and the movement
between them, and that alone settles how the three roll up. Computed lines are
never summed — they are evaluated again over the rolled-up inputs, so the
year's margin is the year's profit over the year's revenue and not twelve
monthly ratios added together. Inputs that are neither flow nor balance, such
as a headcount, state their own rollup.

```python
from decimal import Decimal
from finmodel import (
    Carry, ComputedLine, InputLine, PeriodicModel, Rounding, Statement, Timeline
)

cash = Statement(
    id="cash",
    label="Cash flow",
    rounding=Rounding(2),
    children=[
        InputLine(id="opening_cash", label="Opening cash"),
        InputLine(id="receipts", label="Receipts"),
        InputLine(id="payments", label="Payments"),
        ComputedLine(id="net_cash_flow", label="Net cash flow", formula="receipts - payments"),
        ComputedLine(id="closing_cash", label="Closing cash", formula="opening_cash + net_cash_flow"),
    ],
)

model = PeriodicModel(
    cash,
    carries=[Carry(opening="opening_cash", closing="closing_cash", movement="net_cash_flow")],
)

timeline = Timeline(2026)
months = {
    month.id: {"receipts": Decimal(100 * n), "payments": Decimal("40")}
    for n, month in enumerate(timeline.months, start=1)
}

results = model.run(timeline, months, opening={"opening_cash": Decimal("1000")})

results.amount("2026-Q1", "net_cash_flow")
# Decimal('480.00')
results.amount(timeline.full_year, "closing_cash")
# Decimal('8320.00')
results.row("closing_cash")["2026-01"]
# Decimal('1060.00')
```

The opening balance of a month is never given: the first one comes from the
`opening` mapping, every later one is the previous closing, and handing one in
with the month's values is a `SpecError`.

Stating a movement makes the identity checkable rather than assumed. Every
period — each month, each quarter and the year — carries a `Proof` that opening
plus movement is closing, and a period that fails it raises `IdentityError`
with the proof attached instead of quietly reporting a balance that does not
reconcile.

```python
print(results.proofs("2026")[0])
# closing_cash over 2026: 1000.00 + 7320.00 = 8320.00 (holds)

all(proof.ok for proof in results.proofs())
# True
```

## Does the statement hold together

A signature cannot say that a balance sheet balances. A `Check` says it: two
formulas that must agree over the same period, and the tolerance their
difference may not exceed. A `Checklist` binds checks to a statement, so one
that reads a line the statement does not have is refused there and then. A
failing check names both numbers and the sides they came from.

```python
from decimal import Decimal
from finmodel import (
    Check, CheckError, Checklist, ComputedLine, InputLine, Rounding, Statement
)

sheet = Statement(
    id="balance_sheet",
    label="Balance sheet",
    rounding=Rounding(2),
    children=[
        InputLine(id="cash", label="Cash"),
        InputLine(id="receivables", label="Receivables"),
        ComputedLine(id="total_assets", label="Total assets", formula="cash + receivables"),
        InputLine(id="payables", label="Payables"),
        InputLine(id="equity", label="Equity"),
    ],
)

books = Checklist(
    sheet,
    [Check.balances(assets="total_assets", liabilities="payables", equity="equity")],
)

amounts = sheet.evaluate(
    {
        "cash": Decimal("400"),
        "receivables": Decimal("800"),
        "payables": Decimal("200"),
        "equity": Decimal("950"),
    }
)

print(books.run(amounts)[0])
# Balance sheet balances: total_assets 1200.00 vs payables + equity 1150.00 (off by 50.00)

try:
    books.verify(amounts)
except CheckError as error:
    error.result.left, error.result.right, error.result.difference
    # (Decimal('1200.00'), Decimal('1150.00'), Decimal('50.00'))
```

`Check.balances` and `Check.reconciles` name the two familiar ones — assets
against what funds them, and the cash line of a balance sheet against what the
cash flow closes at — but a check is only two formulas, so any identity a model
leans on can be stated. A tolerance leaves room for stated rounding drift and
nothing more; a side that is `NotApplicable` never holds.

`run` reports, `verify` refuses with a `CheckError` carrying the result, and
`verify_periods` walks a computed timeline — every month, every quarter and the
year — so a rollup that stops balancing is named with the period it broke in.

```python
checked = books.verify_periods(results)
checked["2026-Q1"]
```

## Development

```bash
pip install -e ".[test]"
python -m pytest
```

## License

MIT

Built and maintained by [Shipmind Labs](https://shipmindlabs.com).
