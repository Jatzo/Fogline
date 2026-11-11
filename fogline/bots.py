"""Scripted rulers. Each is a decider: a Brief in, a Reply out, and nothing else.

They see what an LLM ruler will see (tiles relative to their capital, no unmet civ), so the
1,000-tick runs exercise the same path Phase 2 plugs into. Anything a bot remembers between
turns goes back in the reply's memory, which the engine keeps in state.
"""

from fogline.turns import Brief, Reply

# Waypoints sit on square rings round the capital: corners and edge midpoints, 4 tiles apart,
# so each leg reveals fresh ground for a scout that sees 2 tiles each way.
RING_STEP = 4
RING_POINTS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
SKIP_REASONS = {"unreachable", "unknown_ground"}


def spiral_point(leg: int) -> str:
    """The leg-th waypoint of the spiral, as a relative "dx,dy"."""
    ring = leg // len(RING_POINTS) + 1
    dx, dy = RING_POINTS[leg % len(RING_POINTS)]
    return f"{dx * ring * RING_STEP},{dy * ring * RING_STEP}"


def spiral_scout(brief: Brief) -> Reply:
    """Send each idle scout to the next waypoint. A waypoint the engine turned down (sea, or too
    far into unseen land) is already behind the counter, so the bot just checks back next tick."""
    memory = dict(brief["memory"])
    leg = memory.get("leg", 0)
    retry = any(r["kind"] == "move_unit" and r["reason"] in SKIP_REASONS for r in brief["rejections"])
    moves = []
    for unit in brief["units"]:
        if unit["kind"] == "scout" and unit["ready"] and not unit["target"]:
            moves.append({"kind": "move_unit", "unit": unit["id"], "to": spiral_point(leg)})
            leg += 1
    memory["leg"] = leg
    return {"actions": moves,
            "end_turn": {"next_wake": {"ticks": 1 if retry else 8, "triggers": ["unit_arrived", "unit_idle"]}},
            "memory": memory}


def idle(brief: Brief) -> Reply:
    """A ruler that does nothing and checks in every 8 ticks."""
    return {"actions": [], "end_turn": {"next_wake": {"ticks": 8, "triggers": []}}}
