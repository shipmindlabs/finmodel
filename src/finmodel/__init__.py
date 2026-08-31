"""Build financial statements from declarative table specs."""

from finmodel.formula import (
    NA,
    Amount,
    BinaryOp,
    Expr,
    FormulaError,
    NotApplicable,
    Number,
    Reference,
    Rounding,
    UnaryOp,
    Value,
    evaluate,
    parse,
)
from finmodel.spec import (
    Block,
    CircularReferenceError,
    ComputedLine,
    InputLine,
    Line,
    Node,
    SpecError,
    Statement,
    formula_references,
)

__all__ = [
    "NA",
    "Amount",
    "BinaryOp",
    "Block",
    "CircularReferenceError",
    "ComputedLine",
    "Expr",
    "FormulaError",
    "InputLine",
    "Line",
    "Node",
    "NotApplicable",
    "Number",
    "Reference",
    "Rounding",
    "SpecError",
    "Statement",
    "UnaryOp",
    "Value",
    "__version__",
    "evaluate",
    "formula_references",
    "parse",
]

__version__ = "0.1.0"
