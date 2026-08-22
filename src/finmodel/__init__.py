"""Build financial statements from declarative table specs."""

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
    "Block",
    "ComputedLine",
    "InputLine",
    "Line",
    "Node",
    "SpecError",
    "Statement",
    "__version__",
    "formula_references",
]

__version__ = "0.1.0"
