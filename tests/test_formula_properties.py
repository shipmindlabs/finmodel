"""Properties of the evaluator, over formulas generated rather than written."""

import random
import re
from decimal import Decimal

from finmodel import NA, FormulaError, NotApplicable, Rounding, evaluate, parse
from finmodel.formula import to_amount

SEED = 20260913
RUNS = 200
DEPTH = 4
NAMES = ("revenue", "cogs", "opex", "headcount")
LITERALS = ("0", "1", "2", "7", "10", "0.5", "3.125", "12.25", "100")
AMOUNTS = ("0", "1", "-4", "12.5", "0.25", "1000")
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _scope(rng):
    return {name: Decimal(rng.choice(AMOUNTS)) for name in NAMES}


def _apply(op, left, right):
    if isinstance(left, NotApplicable):
        return left
    if isinstance(right, NotApplicable):
        return right
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        return NA
    return left / right


def _expression(rng, scope, depth):
    """A formula and the amount it must come to, built side by side."""
    if depth <= 0 or rng.random() < 0.25:
        if rng.random() < 0.5:
            name = rng.choice(NAMES)
            return name, scope[name]
        literal = rng.choice(LITERALS)
        return literal, Decimal(literal)
    if rng.random() < 0.15:
        text, value = _expression(rng, scope, depth - 1)
        return f"-({text})", value if isinstance(value, NotApplicable) else -value
    op = rng.choice(("+", "-", "*", "/"))
    left_text, left = _expression(rng, scope, depth - 1)
    right_text, right = _expression(rng, scope, depth - 1)
    return f"({left_text} {op} {right_text})", _apply(op, left, right)


def _cases(runs=RUNS, seed=SEED):
    rng = random.Random(seed)
    for _ in range(runs):
        scope = _scope(rng)
        text, value = _expression(rng, scope, DEPTH)
        yield text, scope, value


def _same(left, right):
    """Equal as amounts and, for a decimal, equal to the digit it was stated at."""
    if isinstance(left, NotApplicable) or isinstance(right, NotApplicable):
        return left == right
    return str(left) == str(right)


def test_a_generated_formula_comes_to_its_reference_amount():
    for text, scope, value in _cases():
        assert _same(evaluate(text, scope), value), text


def test_parsing_first_is_the_same_as_evaluating_the_text():
    for text, scope, _ in _cases():
        assert _same(parse(text).evaluate(scope), evaluate(text, scope)), text


def test_references_are_the_names_in_order_of_first_appearance():
    for text, _, _ in _cases():
        assert parse(text).references == tuple(dict.fromkeys(NAME_RE.findall(text)))


def test_whitespace_between_tokens_is_not_part_of_the_formula():
    for text, scope, value in _cases():
        assert _same(evaluate(text.replace(" ", ""), scope), value), text
        loose = text.replace(" ", " \t\n ")
        assert _same(evaluate(f"\n  {loose}  \n", scope), value), text


def test_redundant_parentheses_do_not_change_the_answer():
    for text, scope, value in _cases():
        assert _same(evaluate(f"(({text}))", scope), value), text


def test_a_unary_minus_is_a_subtraction_from_zero():
    for text, scope, _ in _cases():
        assert evaluate(f"-({text})", scope) == evaluate(f"0 - ({text})", scope), text


def test_multiplication_binds_tighter_than_addition():
    rng = random.Random(SEED + 1)
    for _ in range(RUNS):
        scope = _scope(rng)
        a, b, c = rng.sample(NAMES, 3)
        assert evaluate(f"{a} + {b} * {c}", scope) == scope[a] + scope[b] * scope[c]
        assert evaluate(f"{a} - {b} * {c}", scope) == scope[a] - scope[b] * scope[c]
        assert evaluate(f"({a} + {b}) * {c}", scope) == (scope[a] + scope[b]) * scope[c]


def test_the_operations_group_from_the_left():
    rng = random.Random(SEED + 2)
    for _ in range(RUNS):
        scope = _scope(rng)
        a, b, c = rng.sample(NAMES, 3)
        assert evaluate(f"{a} - {b} - {c}", scope) == evaluate(
            f"({a} - {b}) - {c}", scope
        )
        assert evaluate(f"{a} / {b} / {c}", scope) == evaluate(
            f"({a} / {b}) / {c}", scope
        )
        assert evaluate(f"{a} + {b}", scope) == evaluate(f"{b} + {a}", scope)


def test_a_division_by_zero_reaches_everything_that_reads_it():
    for text, scope, _ in _cases(50):
        assert evaluate(f"({text}) + (1 / 0)", scope) == NA
        assert evaluate(f"(1 / 0) * ({text})", scope) == NA
        assert evaluate(f"-((1 / 0) - ({text}))", scope) == NA


def test_arbitrary_text_is_refused_as_a_formula_error_or_not_at_all():
    rng = random.Random(SEED + 3)
    scope = {"a": Decimal(3), "b": Decimal(0)}
    for _ in range(500):
        text = "".join(rng.choice("ab_ 019+-*/().,%$#@\t\n") for _ in range(12))
        try:
            amount = evaluate(text[: rng.randint(0, 12)], scope)
        except FormulaError:
            continue
        assert isinstance(amount, (Decimal, NotApplicable))


def test_amounts_never_become_binary_floats():
    assert evaluate("a + b", {"a": 0.1, "b": 0.2}) == Decimal("0.3")
    assert evaluate("a + b - c", {"a": 0.1, "b": 0.2, "c": "0.3"}) == Decimal(0)
    rng = random.Random(SEED + 4)
    for _ in range(RUNS):
        number = round(rng.uniform(-1000, 1000), rng.randint(0, 6))
        assert to_amount(number, "line") == Decimal(repr(number))


def test_rounding_is_idempotent_and_lands_on_its_own_scale():
    rng = random.Random(SEED + 5)
    for _ in range(RUNS):
        digits = rng.randint(0, 4)
        rounding = Rounding(digits)
        amount = Decimal(rng.randint(-(10**7), 10**7)).scaleb(-rng.randint(0, 6))
        once = rounding.apply(amount)
        assert once.as_tuple().exponent == -digits
        assert rounding.apply(once) == once
        assert abs(once - amount) <= rounding.exponent / 2


def test_rounding_moves_a_tie_away_from_zero():
    rng = random.Random(SEED + 6)
    rounding = Rounding(2)
    for _ in range(RUNS):
        units = rng.randint(0, 10**6)
        tie = Decimal(units * 10 + 5).scaleb(-3)
        assert rounding.apply(tie) == Decimal(units + 1).scaleb(-2)
        assert rounding.apply(-tie) == -Decimal(units + 1).scaleb(-2)


def test_rounding_leaves_a_stated_non_answer_alone():
    assert Rounding(2).apply(NA) is NA
