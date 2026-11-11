"""What each civ thinks of each other civ (docs/rules.md section 11).

Held per ordered pair: state["reputation"][a][b] is a's view of b, from -100 to 100. Every civ
starts with the same view of b, set by b's temperament; acts move it (Phase 3 trade, Phase 5
raids) and it drifts back towards the start. A ruler only ever sees the word, never the number.
"""

from fogline.config import Config

WORDS = ((60, "trusted"), (20, "friendly"), (-19, "unknown"), (-59, "wary"))  # else "hostile"


def start(config: Config, civ_id: str) -> int:
    spec = config.civ(civ_id)
    return 20 * (spec.generosity - spec.ruthlessness) // 1000


def initial(config: Config, civ_ids: list[str]) -> dict[str, dict[str, int]]:
    return {a: {b: start(config, b) for b in sorted(civ_ids) if b != a} for a in sorted(civ_ids)}


def word(value: int) -> str:
    return next((name for floor, name in WORDS if value >= floor), "hostile")


def change(state: dict, viewer: str, subject: str, amount: int) -> None:
    views = state["reputation"][viewer]
    views[subject] = max(-100, min(100, views[subject] + amount))


def drift(config: Config, state: dict, now: int) -> None:
    """Every reputation_drift_every ticks each view moves 1 point back towards its start."""
    if now == 0 or now % config.reputation_drift_every:
        return
    for viewer in sorted(state["reputation"]):
        for subject in sorted(state["reputation"][viewer]):
            value, home = state["reputation"][viewer][subject], start(config, subject)
            if value != home:
                state["reputation"][viewer][subject] = value + (1 if value < home else -1)
