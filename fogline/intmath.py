"""Integer arithmetic helpers.

All state is integer so that state hashes match on every machine (docs/rules.md section 0).
Every division in the engine goes through these helpers, so the rounding rule lives in one place.
"""

PER_MILLE = 1000


def floor_div(numerator: int, denominator: int) -> int:
    """Round down towards minus infinity, the default rounding in rules.md."""
    if denominator == 0:
        raise ZeroDivisionError("floor_div by zero")
    return numerator // denominator


def ceil_div(numerator: int, denominator: int) -> int:
    """Round up towards plus infinity, used where a rule says "rounded up" (deaths, tool wear)."""
    if denominator == 0:
        raise ZeroDivisionError("ceil_div by zero")
    return -((-numerator) // denominator)


def per_mille(value: int, rate: int) -> int:
    """Apply a per-mille rate (1000 = 100%) to a value, rounding down."""
    return floor_div(value * rate, PER_MILLE)
