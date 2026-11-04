# finmodel

Build financial statements from declarative table specs: P&L, cash flow and
balance sheet, with a safe formula evaluator instead of `eval()`.

## Status

Pre-alpha. Statements can be declared and validated, formulas parse and
evaluate over a closed table of functions, a single period computes with
per-line rounding, twelve months roll into quarters and a year with balances
carried across the boundaries, checks state what the numbers must agree on, and
a computed statement renders to one table model with Markdown and CSV writers
over it.

## Installation

```bash
pip install finmodel
```

## Financial models as data, not spreadsheets

A spreadsheet keeps the model in its cells. The formula lives where the number
is shown, a reference is a coordinate rather than a name, and a year is twelve
copies of the same arithmetic side by side. The file cannot answer what gross
margin depends on, cannot say that a row was inserted through the middle of a
range, and cannot be reviewed except one cell at a time.

finmodel keeps the model in data. A statement is a tree of frozen dataclasses:
blocks group categories, input lines take values per period, computed lines
carry a formula that names other lines by id. Constructing the tree validates
it — identifiers, duplicates, formula syntax, unknown references, cycles — and
parses every formula once, so the dependency graph and the order the lines must
be evaluated in are known before a single number is supplied. The twelve months
of a year are that one spec evaluated twelve times, not twelve copies of it.

There is no file format of its own. A spec is ordinary Python objects, so
loading one from JSON, YAML or a database is a loader you write, and a loaded
spec is validated exactly like a hand-written one.

## The spec format

A statement is a root node over three kinds of child.

| Node | What it is | Carries |
| --- | --- | --- |
| `Block` | a named group of lines and nested blocks | `id`, `label`, `children` |
| `InputLine` | a row whose values are supplied per period | `id`, `label`, `rounding`, `unit` |
| `ComputedLine` | a row derived from other lines | `id`, `label`, `rounding`, `formula` |
| `Statement` | the root that computes and validates | `id`, `label`, `children`, `rounding` |

Nesting is for reading, not for scope. Ids are flat across the whole statement,
so a formula in one block may name a line in another, and a duplicate id is
refused wherever it appears.

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

What construction refuses, and the `SpecError` it refuses with:

| The spec says | The error reads |
| --- | --- |
| an id that is not an identifier | `line id must be an identifier, got 'total revenue'` |
| an id the grammar already uses | `line id 'min' is a function name of the grammar` |
| the same id twice | `duplicate id 'services'` |
| a blank label | `label of 'cogs' must not be empty` |
| an empty block or statement | `block 'revenue' must contain at least one child` |
| a computed line with no formula | `computed line 'gross_profit' must have a formula` |
| a formula outside the grammar | `formula of 'gross_profit' is invalid: ...` |
| a reference to nothing | `line 'gross_profit' references unknown line 'cgos'` |
| a reference to a block | `line 'x' references block 'revenue'; formulas may only reference lines` |
| lines that depend on one another | `circular reference: ebit -> ebitda -> ebit` |

A built statement answers questions about itself: `lines`, `input_lines`,
`computed_lines` and `walk()` for the shape, `line(id)` for one row,
`rounding_of(id)` for the scale it will state its amounts at, and
`dependency_graph` for the edges between them. Every `ComputedLine` carries
its parsed tree as `line.expression` and the ids it reads as
`line.references`; `formula_references(formula)` answers the same question for
a formula that is not attached to a line yet.

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

## The formula grammar

A formula is tokenised and parsed by recursive descent into a small expression
tree, then evaluated over an explicit scope. The whole language is five
productions:

```
expression = sum
sum        = product (( "+" | "-" ) product)*
product    = signed (( "*" | "/" ) signed)*
signed     = ( "+" | "-" ) signed | atom
atom       = number | call | name | "(" sum ")"
call       = function "(" sum ( "," sum )* ")"

function   = "abs" | "max" | "min"
number     = digits [ "." [ digits ] ] | "." digits
name       = [A-Za-z_][A-Za-z0-9_]*
```

Products bind tighter than sums, both group from the left, a sign may be
repeated, and whitespace between tokens is not part of the formula. A `name` is
a reference to another line of the same statement, read from the scope at
evaluation time; a `number` becomes an exact `Decimal` literal; a `call` names
one function of the closed table below, and nothing else is callable.

The tree is five node types — `Number`, `Reference`, `UnaryOp`, `BinaryOp`,
`Call` — each frozen, each answering `references` and `evaluate(scope)`.

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

Everything else is a `FormulaError` that names the position it gave up at:

| The formula says | The error reads |
| --- | --- |
| `cogs > 0` | `unexpected character '>' at position 5` |
| `revenue.upper()` | `unexpected character '.' at position 7` |
| `SUM(a:b)` | `unexpected character ':' at position 5` |
| `2 ** 3` | `unexpected '*' at position 3` |
| `revenue if revenue else 0` | `unexpected 'if' at position 8` |
| `(total_revenue - cogs` | `expected ')' at position 21` |
| `revenue -` | `unexpected end of formula` |
| `sum(a, b)` | `unknown function 'sum' at position 0` |
| `min(revenue)` | `min takes at least 2 arguments, got 1 at position 0` |
| `max` | `function 'max' is not a line reference at position 0` |

A name the scope does not bind is a `FormulaError` too — `unbound reference
'cgos'` — but inside a statement it never gets that far: references are
resolved against the lines when the statement is built.

Numbers and names are ASCII. A digit from another script is an unexpected
character rather than a number, so what the tokeniser accepts is exactly what
the grammar above writes down.

Nesting is bounded. A formula may nest `MAX_DEPTH` levels — 128, counted over
parentheses, a chain of operations, repeated signs and calls alike — and one
that nests deeper is a `FormulaError` naming the position it passed the bound
at, rather than a `RecursionError` from inside the parser.

## A closed table of functions

A formula may call a function, but only one the grammar itself names. `FUNCTIONS`
is that table, read-only, and three entries long.

| Call | Takes | Answers |
| --- | --- | --- |
| `abs(x)` | exactly 1 argument | the magnitude of its argument |
| `max(a, b, ...)` | at least 2 arguments | the greatest of its arguments |
| `min(a, b, ...)` | at least 2 arguments | the least of its arguments |

A call is an atom: it takes a sign, multiplies, nests inside another call and
counts against the depth bound like a parenthesis. The number of arguments is
checked when the formula is parsed — not when a period is computed — and the
error names the position the function name stood at. Arguments are evaluated
left to right and the first `NotApplicable` is the answer of the whole call,
exactly as a non-answer propagates through an operation, so a function is never
handed one as a number.

```python
from decimal import Decimal
from finmodel import FUNCTIONS, evaluate, parse

sorted(FUNCTIONS)
# ['abs', 'max', 'min']

evaluate("max(profit, 0) * 0.25", {"profit": Decimal("400")})
# Decimal('100.00')
evaluate("abs(min(profit, 0))", {"profit": Decimal("-500")})
# Decimal('500')
evaluate("abs(profit / revenue)", {"profit": Decimal("90"), "revenue": Decimal("0")})
# NotApplicable(reason='division by zero')

parse("min(revenue, cogs, 0)").references
# ('revenue', 'cogs')
```

A function name belongs to the grammar, never to a statement. `max` standing on
its own is a `FormulaError` rather than a reference, and a line or block whose
id is `min`, `max` or `abs` is refused when it is constructed — a formula could
not tell the two apart. Names are case-sensitive, so `ABS(a)` is an unknown
function rather than `abs`.

## Why `eval()` is not an option

The obvious implementation of a formula language in Python is one line:
`eval(formula, {"__builtins__": {}}, scope)`. It is not used here, for four
reasons, and only the first is about security.

**A spec is input.** Hand-written today, loaded from a file or a form
tomorrow — and `eval` over a string reaches the whole interpreter through
attribute access on any object it can see, whatever the namespace was emptied
of. Sandboxing it is a game that has been lost repeatedly. A grammar whose only
calls are the three functions it names, with no attributes and no subscripts,
has nothing to escape from.

**Parsing is what gives you the references.** `evaluation_order`,
`dependency_graph`, the cycle error and the refusal of an unknown line all come
from walking the tree before any value exists. `eval` reports a missing name
only when the line is computed, only one at a time, and cannot be asked what a
formula depends on at all.

**Python's arithmetic is not a statement's arithmetic.** Division by zero
raises where a model wants to state that a margin is not applicable. A literal
like `0.1` is binary floating point, and mixing it with a `Decimal` is a
`TypeError` rather than an amount. Integer operands, `**`, `//` and comparison
chaining all mean something in Python that a table of money should not have to
inherit.

**Errors land in the wrong place.** A `SyntaxError` over a fragment of a
formula says nothing about which line carried it. Here the formula is parsed
when the `ComputedLine` is constructed, so a malformed formula is a `SpecError`
naming that line, at the moment the model is declared rather than the moment it
is run.

## Money, rounding and division by zero

Amounts are `Decimal` end to end. Integers, floats and strings handed in through
a scope are converted exactly — a float through its shortest repr — so nothing
reaches the arithmetic as binary floating point.

A value that is not finite is refused where it enters. A NaN or an infinity
arriving as a float, a string or a `Decimal` is a `FormulaError` naming the line
that held it, instead of a rounding that fails late or a check comparison that
raises `InvalidOperation` two layers away.

Rounding is stated, never implicit. A `Rounding` carries a number of decimal
places and a mode from the `decimal` module, defaulting to `ROUND_HALF_UP`
rather than the banker's rounding of `decimal` itself. Lines state their own; a
statement may state a default for the lines that do not. Negative digits round
to units of ten.

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
cash flow closes at — but a check is only two formulas over the same grammar,
so any identity a model leans on can be stated. A tolerance leaves room for
stated rounding drift and nothing more; a side that is `NotApplicable` never
holds.

`run` reports, `verify` refuses with a `CheckError` carrying the result, and
`verify_periods` walks a computed timeline — every month, every quarter and the
year — so a rollup that stops balancing is named with the period it broke in.

```python
checked = books.verify_periods(results)
checked["2026-Q1"]
```

## One table, two writers

Numbers are shown from the spec that computed them. `tabulate` walks the
statement in declaration order and returns a `Table`: block headers at their
nesting depth, then the lines, with one column per period. `render_markdown`
and `render_csv` write that single model, neither of them knowing anything
about statements, so a third writer is a function over `Table.rows`.

What goes in decides the columns. A `Results` becomes one column per period of
its timeline, a mapping of period to amounts becomes those columns in the order
given, and one period's amounts become a single column named `Amount`. The
first header cell is the statement label.

```python
from decimal import Decimal
from finmodel import (
    Block,
    ComputedLine,
    InputLine,
    Rounding,
    Statement,
    render_csv,
    render_markdown,
    tabulate,
)

statement = Statement(
    id="pnl",
    label="Profit and loss",
    rounding=Rounding(2),
    children=[
        Block(
            id="revenue",
            label="Revenue",
            children=[
                InputLine(id="subscriptions", label="Subscriptions", unit="USD"),
                InputLine(id="services", label="Services", unit="USD"),
                ComputedLine(
                    id="total_revenue",
                    label="Total revenue",
                    formula="subscriptions + services",
                ),
            ],
        ),
        InputLine(id="cogs", label="Cost of revenue", unit="USD"),
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

amounts = statement.evaluate(
    {
        "subscriptions": Decimal("800000"),
        "services": Decimal("200000"),
        "cogs": Decimal("200000"),
    }
)

print(render_markdown(tabulate(statement, amounts)))
```

```
| Profit and loss       |     Amount |
| :-------------------- | ---------: |
| **Revenue**           |            |
|   Subscriptions (USD) |  800000.00 |
|   Services (USD)      |  200000.00 |
|   Total revenue       | 1000000.00 |
| Cost of revenue (USD) |  200000.00 |
| Gross profit          |  800000.00 |
| Gross margin          |     0.8000 |
```

Cells are text exactly as the amounts state themselves: a line rounded to two
places prints two places, a line rounded to four prints four, and a
`NotApplicable` prints its reason — `n/a (division by zero)` — rather than a
blank that would read like a zero. A unit stated on an `InputLine` follows the
label. A block header holds no amounts, and a pipe inside a label is escaped,
so a label cannot break a row.

CSV carries the ids, the depth and the unit beside the same cells, so a table
written out can be read back into the rows it came from.

```python
print(render_csv(tabulate(statement, amounts)))
```

```
id,label,depth,unit,Amount
revenue,Revenue,0,,
subscriptions,Subscriptions,1,USD,800000.00
services,Services,1,USD,200000.00
total_revenue,Total revenue,1,,1000000.00
cogs,Cost of revenue,0,USD,200000.00
gross_profit,Gross profit,0,,800000.00
gross_margin,Gross margin,0,,0.8000
```

A computed timeline needs no extra work: hand the `Results` over for every
period it holds, or a mapping of the periods wanted for a narrower table. A
`Table` is also readable by id, so a report can pull one cell without parsing
what it just wrote.

```python
table = tabulate(cash, results)
table.columns
# ('2026-01', '2026-02', ..., '2026-Q1', ..., '2026')
table.amount("closing_cash", "2026-Q1")
# Decimal('1480.00')
table.row("closing_cash").cells[0]
# '1060.00'

quarters = tabulate(cash, {period: results[period] for period in timeline.quarters})
quarters.columns
# ('2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4')
```

A column that has no amount for a line is a `SpecError` naming both, as is a
mapping that mixes periods with amounts: a table is either complete or refused,
the same way a period is.

## Errors

| Error | Base | Raised when | Carries |
| --- | --- | --- | --- |
| `FormulaError` | `ValueError` | a formula is outside the grammar or nests too deep, a call names a function the table does not hold or takes the wrong number of arguments, a name is unbound, or a value is not a finite number | the position it gave up at |
| `SpecError` | `ValueError` | a spec is structurally invalid, or a period's values do not fit it | — |
| `CircularReferenceError` | `SpecError` | computed lines depend on one another | `cycle` |
| `IdentityError` | `SpecError` | closing is not opening plus movement | `proof` |
| `CheckError` | `SpecError` | the two sides of a check disagree | `result`, `where` |

A malformed formula inside a `ComputedLine` surfaces as a `SpecError` naming
the line, with the `FormulaError` as its cause.

## Development

```bash
pip install -e ".[test]"
python -m pytest
```

## License

MIT

Built and maintained by [Shipmind Labs](https://shipmindlabs.com).
