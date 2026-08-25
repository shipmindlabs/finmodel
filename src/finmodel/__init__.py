"""Build financial statements from declarative table specs."""

from finmodel.formula import (
    BinaryOp,
    Expr,
    FormulaError,
    Number,
    Reference,
    UnaryOp,
    evaluate,
    parse,
)
from finmodel.spec import (
    Block,
    ComputedLine,
    InputLine,
    Line,
    Node,
    SpecError,
    Statement,
    formula_references,
)

__all__ = [
    "BinaryOp",
    "Block",
    "ComputedLine",
    "Expr",
    "FormulaError",
    "InputLine",
    "Line",
    "Node",
    "Number",
    "Reference",
    "SpecError",
    "Statement",
    "UnaryOp",
    "__version__",
    "evaluate",
    "formula_references",
    "parse",
]

__version__ = "0.1.0"
