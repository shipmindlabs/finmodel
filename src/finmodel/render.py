"""One table model from a spec and its amounts, with Markdown and CSV writers."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from finmodel.formula import Amount, Value, to_amount
from finmodel.periods import Period, Results
from finmodel.spec import Block, InputLine, SpecError, Statement

__all__ = [
    "AMOUNT_COLUMN",
    "BLOCK",
    "COMPUTED",
    "INPUT",
    "Row",
    "Table",
    "render_csv",
    "render_markdown",
    "tabulate",
]

BLOCK = "block"
INPUT = "input"
COMPUTED = "computed"

AMOUNT_COLUMN = "Amount"


@dataclass(frozen=True)
class Row:
    """One row of a table: a block header, or a line and its amounts."""

    id: str
    label: str
    depth: int
    kind: str
    unit: str | None = None
    amounts: tuple[Amount | None, ...] = ()

    @property
    def is_header(self) -> bool:
        return self.kind == BLOCK

    @property
    def title(self) -> str:
        """The label as it is shown, carrying the unit the line states."""
        return f"{self.label} ({self.unit})" if self.unit else self.label

    @property
    def cells(self) -> tuple[str, ...]:
        """The amounts as text: a header holds none, a non-answer its reason."""
        return tuple("" if amount is None else str(amount) for amount in self.amounts)


@dataclass(frozen=True)
class Table:
    """Rows in declaration order, one column per period, ready to be written."""

    label: str
    columns: Sequence[str] = ()
    rows: Sequence[Row] = ()
    _index: dict[str, Row] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "_index", {row.id: row for row in self.rows})

    def row(self, row_id: str) -> Row:
        try:
            return self._index[row_id]
        except KeyError:
            raise SpecError(f"unknown row {row_id!r}") from None

    def amount(self, row_id: str, column: str) -> Amount | None:
        """One cell, by row id and column name."""
        row = self.row(row_id)
        try:
            position = tuple(self.columns).index(column)
        except ValueError:
            raise SpecError(f"unknown column {column!r}") from None
        return row.amounts[position]


def tabulate(statement: Statement, results_or_amounts: Results | Mapping) -> Table:
    """Build the table of a statement: block headers at their depth, then lines.

    A `Results` becomes one column per period of its timeline, a mapping of
    period to amounts becomes those columns in the order given, and one
    period's amounts become a single column named `Amount`.
    """
    frames = _frames(results_or_amounts)
    rows: list[Row] = []
    for node, depth in statement.walk():
        if isinstance(node, Block):
            rows.append(
                Row(
                    id=node.id,
                    label=node.label,
                    depth=depth,
                    kind=BLOCK,
                    amounts=(None,) * len(frames),
                )
            )
            continue
        is_input = isinstance(node, InputLine)
        rows.append(
            Row(
                id=node.id,
                label=node.label,
                depth=depth,
                kind=INPUT if is_input else COMPUTED,
                unit=node.unit if is_input else None,
                amounts=tuple(
                    _cell(frame, node.id, column) for column, frame in frames.items()
                ),
            )
        )
    return Table(label=statement.label, columns=tuple(frames), rows=tuple(rows))


def render_markdown(table: Table) -> str:
    """The table as a Markdown pipe table: headers in bold, amounts to the right."""
    header = (_escape(table.label), *(_escape(column) for column in table.columns))
    body = [
        (_title(row), *(_escape(cell) for cell in row.cells)) for row in table.rows
    ]
    widths = [max(3, *(len(cell) for cell in column)) for column in zip(header, *body)]
    lines = [_pipes(header, widths), _rule(widths)]
    lines.extend(_pipes(cells, widths) for cells in body)
    return "\n".join(lines) + "\n"


def render_csv(table: Table) -> str:
    """The table as CSV: ids, depth and unit beside the same cells."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("id", "label", "depth", "unit", *table.columns))
    for row in table.rows:
        writer.writerow((row.id, row.label, row.depth, row.unit or "", *row.cells))
    return buffer.getvalue()


def _frames(source: Results | Mapping) -> dict[str, Mapping[str, Value]]:
    if isinstance(source, Results):
        return {period.id: source[period] for period in source.periods}
    if not isinstance(source, Mapping):
        raise SpecError(f"cannot tabulate {type(source).__name__}")
    nested = [isinstance(value, Mapping) for value in source.values()]
    if nested and all(nested):
        return {_column(key): value for key, value in source.items()}
    if any(nested):
        raise SpecError("columns must either all be periods or all be amounts")
    return {AMOUNT_COLUMN: source}


def _column(key: object) -> str:
    return key.id if isinstance(key, Period) else str(key)


def _cell(frame: Mapping[str, Value], line_id: str, column: str) -> Amount:
    try:
        value = frame[line_id]
    except KeyError:
        raise SpecError(
            f"no amount for line {line_id!r} in column {column!r}"
        ) from None
    return to_amount(value, line_id)


def _title(row: Row) -> str:
    indent = "  " * row.depth
    title = _escape(row.title)
    return f"{indent}**{title}**" if row.is_header else indent + title


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def _pipes(cells: Sequence[str], widths: Sequence[int]) -> str:
    padded = [
        cell.ljust(width) if position == 0 else cell.rjust(width)
        for position, (cell, width) in enumerate(zip(cells, widths))
    ]
    return "| " + " | ".join(padded) + " |"


def _rule(widths: Sequence[int]) -> str:
    cells = [":" + "-" * (widths[0] - 1)]
    cells.extend("-" * (width - 1) + ":" for width in widths[1:])
    return "| " + " | ".join(cells) + " |"
