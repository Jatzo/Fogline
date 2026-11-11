"""The ledger: the only way a conserved stock changes.

Every unit of food, timber, stone, metal, luxury, population or node stock that appears or
disappears passes through apply() with a named rule (docs/rules.md section 0, conservation).
The state keeps running totals per (owner, stock); the full per-tick log is written outside
the hashed state by the runner, because it grows without bound.
"""

from enum import StrEnum
from typing import Any

STOCKS = ("food", "timber", "stone", "metal", "luxury", "pop", "node")


class Rule(StrEnum):
    """Every reason a stock may change. Adding a reason means adding it here, on purpose."""

    WORLDGEN = "worldgen"
    PRODUCTION = "production"
    EXTRACTION = "extraction"  # node stock falling as it is worked
    REGROWTH = "regrowth"  # forest nodes regrowing
    EATING = "eating"
    SPOILAGE = "spoilage"
    FUEL = "fuel"
    UPKEEP = "upkeep"
    TOOL_WEAR = "tool_wear"
    LUXURY_USE = "luxury_use"
    BUILD_COST = "build_cost"
    RESEARCH_COST = "research_cost"
    TRAIN_COST = "train_cost"
    UNIT_UPKEEP = "unit_upkeep"
    RIOT = "riot"
    BIRTH = "birth"
    DEATH_STARVATION = "death_starvation"
    DEATH_COLD = "death_cold"
    DEATH_PLAGUE = "death_plague"
    TRAINED = "trained"  # people leaving the population to serve in a unit
    DISBANDED = "disbanded"  # people returning from a unit
    DISCOVERY = "discovery"  # Providence mineral discovery creates a node
    SUPPLY = "supply"  # test-only top-up standing in for trade (ADR 0004)


class LedgerError(ValueError):
    """Raised when a change would break conservation or use an unknown stock."""


def apply(
    stocks: dict[str, int],
    totals: dict[str, int],
    log: list[dict[str, Any]] | None,
    owner: str,
    stock: str,
    delta: int,
    rule: Rule,
    tick: int,
) -> None:
    """Change one stock by delta for a named rule, refusing to go below zero.

    stocks: the owner's stock dict inside state, changed in place.
    totals: the running net change per "owner:stock:rule", kept in state.
    log: the per-tick log kept outside state, or None when not recording.
    """
    if stock not in STOCKS:
        raise LedgerError(f"unknown stock {stock!r}")
    if not isinstance(rule, Rule):
        raise LedgerError(f"rule must be a ledger.Rule, got {rule!r}")
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise LedgerError(f"delta must be an int, got {delta!r}")
    if delta == 0:
        return
    current = stocks.get(stock, 0)
    if current + delta < 0:
        raise LedgerError(f"{owner} {stock} would go below zero ({current} + {delta}) under {rule}")
    stocks[stock] = current + delta
    key = f"{owner}:{stock}:{rule.value}"
    totals[key] = totals.get(key, 0) + delta
    if log is not None:
        log.append({"tick": tick, "owner": owner, "stock": stock, "delta": delta, "rule": rule.value})


def net_change(totals: dict[str, int], owner: str, stock: str) -> int:
    """Sum of every recorded change to one owner's stock, across all rules."""
    prefix = f"{owner}:{stock}:"
    return sum(value for key, value in totals.items() if key.startswith(prefix))
