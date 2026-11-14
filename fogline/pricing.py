"""What a ruler call costs at list prices, worked out from its token counts.

`claude -p` reports a cost of its own, but it doesn't know every model: for claude-haiku-5-5 it
says `costBasis: "unknown"` and charges Opus 5.5 rates, about 40 times too much (docs/debug-log.md).
So the runner and the viewer price each call here and keep the reported figure only as a record.

Rates are US dollars per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing,
read on 2026-11-14. Change them here, with the date, when the page changes.
"""

from dataclasses import dataclass

PRICES_READ_ON = "2026-11-14"
DEFAULT_MODEL = "claude-haiku-5-5"  # every ruler, before the roster (runs whose manifest names none)


@dataclass(frozen=True)
class Rates:
    input: float
    write_5m: float
    write_1h: float
    read: float
    output: float


RATES = {
    "claude-haiku-5-5": Rates(0.10, 0.125, 0.20, 0.01, 0.50),
    "claude-sonnet-5-5": Rates(2.00, 2.50, 4.00, 0.10, 10.00),
    "claude-opus-5-5": Rates(4.00, 5.00, 8.00, 0.20, 20.00),
}
# Haiku 5.5 charges more for a prompt over 100,000 tokens (input, writes and reads together).
LONG_PROMPT = 100_000
LONG_RATES = {"claude-haiku-5-5": Rates(0.50, 0.625, 1.00, 0.05, 2.50)}


class UnknownModel(ValueError):
    pass


def rates_for(model: str, prompt_tokens: int = 0) -> Rates:
    if model not in RATES:
        raise UnknownModel(f"no price for {model}; add it to fogline/pricing.py with the date")
    if prompt_tokens > LONG_PROMPT and model in LONG_RATES:
        return LONG_RATES[model]
    return RATES[model]


def cost(model: str, usage: dict | None, unsplit_writes: str = "1h") -> float:
    """Dollars for one call. Cache writes are priced by their 5-minute and 1-hour parts when the
    call recorded them; calls stored before that are priced as `unsplit_writes` ("1h" or "5m")."""
    if not usage:
        return 0.0
    plain, writes, reads = (usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                       "cache_read_input_tokens"))
    rates = rates_for(model, plain + writes + reads)
    if "cache_write_1h" in usage or "cache_write_5m" in usage:
        long_writes, short_writes = usage.get("cache_write_1h", 0), usage.get("cache_write_5m", 0)
    elif unsplit_writes == "5m":
        long_writes, short_writes = 0, writes
    else:
        long_writes, short_writes = writes, 0
    return (plain * rates.input + short_writes * rates.write_5m + long_writes * rates.write_1h
            + reads * rates.read + usage.get("output_tokens", 0) * rates.output) / 1_000_000


def row_cost(row: dict, default_model: str = DEFAULT_MODEL, unsplit_writes: str = "1h") -> float:
    """The cost of one stored output row, under the model it records or the run's model for its civ."""
    return cost(row.get("model") or default_model, row.get("usage"), unsplit_writes)
