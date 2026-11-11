"""Scripted rulers. Each is a decider: a Brief in, a Reply out, and nothing else.

They see what an LLM ruler will see (tiles relative to their capital, no unmet civ), so the
1,000-tick runs exercise the same path Phase 2 plugs into. Anything a bot remembers between
turns goes back in the reply's memory, which the engine keeps in state.
"""

import copy

from fogline import techs
from fogline.config import Config
from fogline.intmath import ceil_div
from fogline.state import parse_tile_key
from fogline.turns import Brief, Decider, Reply

# Waypoints sit on square rings round the capital: corners and edge midpoints, 4 tiles apart,
# so each leg reveals fresh ground for a scout that sees 2 tiles each way.
RING_STEP = 4
RING_POINTS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
SKIP_REASONS = {"unreachable", "unknown_ground"}

RESEARCH_FIRST = ("writing", "crop_rotation")
FOOD_SHORT_FIRST = ("crop_rotation", "writing")  # a civ short of food needs its farms first
TREE_ORDER = list(techs.TECHS)
BLOCK_TICKS = 8  # after a rejected build, leave that building in that settlement alone this long
BALANCE_TICKS = 4
HOUSING_TIMBER = 100  # housing pauses while timber falls only once the stock is under this
FIELD_WORK = ("farm", "mine", "lumber_camp")  # buildings whose slots count as jobs when placing a farm


def spiral_point(leg: int) -> str:
    """The leg-th waypoint of the spiral, as a relative "dx,dy"."""
    ring = leg // len(RING_POINTS) + 1
    dx, dy = RING_POINTS[leg % len(RING_POINTS)]
    return f"{dx * ring * RING_STEP},{dy * ring * RING_STEP}"


def _scout_moves(brief: Brief, memory: dict) -> tuple[list[dict], bool]:
    """Orders for idle scouts, and whether a waypoint was turned down last turn. A turned-down
    waypoint is already behind the counter, so the caller just checks back sooner."""
    leg = memory.get("leg", 0)
    retry = any(r["kind"] == "move_unit" and r["reason"] in SKIP_REASONS for r in brief["rejections"])
    moves = []
    for unit in brief["units"]:
        if unit["kind"] == "scout" and unit["ready"] and not unit["target"]:
            moves.append({"kind": "move_unit", "unit": unit["id"], "to": spiral_point(leg)})
            leg += 1
    memory["leg"] = leg
    return moves, retry


def spiral_scout(brief: Brief) -> Reply:
    """Send each idle scout to the next waypoint of a widening spiral."""
    memory = dict(brief["memory"])
    moves, retry = _scout_moves(brief, memory)
    return {"actions": moves,
            "end_turn": {"next_wake": {"ticks": 1 if retry else 8, "triggers": ["unit_arrived", "unit_idle"]}},
            "memory": memory}


def idle(brief: Brief) -> Reply:
    """A ruler that does nothing and checks in every 8 ticks."""
    return {"actions": [], "end_turn": {"next_wake": {"ticks": 8, "triggers": []}}}


def make_builder(config: Config, food_short: bool = False) -> Decider:
    """The scripted builder (rules 21, M6). It never trades and never claims a contestable node,
    so it is the isolation baseline and the civ the run-out schedule is measured on. A food-short
    civ researches Crop rotation before Writing."""
    first = FOOD_SHORT_FIRST if food_short else RESEARCH_FIRST

    def count(settlement: dict, building: str) -> int:
        return settlement["buildings"].count(building)

    def decide(brief: Brief) -> Reply:
        memory = copy.deepcopy(brief["memory"])
        now = brief["tick"]
        stocks = brief["stocks"]
        actions: list[dict] = []
        sent: list[str] = []

        # Remember stocks, so a 4-tick balance can be read off the history.
        history = [h for h in memory.get("history", []) if h[0] >= now - 2 * BALANCE_TICKS]
        history.append([now, stocks["food"], stocks["timber"], stocks["stone"], stocks["metal"]])
        memory["history"] = history

        def balance(column: int) -> int:
            older = [h for h in history if h[0] <= now - BALANCE_TICKS]
            return history[-1][column] - older[-1][column] if older else 0

        blocked = {key: until for key, until in memory.get("blocked", {}).items() if until > now}
        for rejection in brief["rejections"]:
            index = rejection["index"]
            if 0 <= index < len(memory.get("sent", [])) and memory["sent"][index]:
                blocked[memory["sent"][index]] = now + BLOCK_TICKS

        def add(action: dict, key: str = "") -> bool:
            if key and key in blocked:
                return False
            actions.append(action)
            sent.append(key)
            return True

        # Research never stops: Writing first, then Crop rotation, then the cheapest era in tree order.
        options = brief["research"]["available"]
        if not brief["research"]["tech"] and options:
            pick = next((t for t in first if t in options), None)
            pick = pick or min(options, key=lambda t: (techs.TECHS[t].era, TREE_ORDER.index(t)))
            add({"kind": "set_research", "tech": pick})

        settlements = brief["settlements"]
        capital = next(s for s in settlements if s["tile"] == "0,0")
        outposts = [s for s in settlements if s is not capital]

        # Keep every scholar slot in the capital staffed; food takes what the fixed lines leave.
        scholars = (count(capital, "workshop") * config.slots["workshop"]
                    + count(capital, "library") * config.slots["library"])
        research = min(50, ceil_div(100 * scholars, max(capital["pop"], 1)))
        allocation = {"timber": 15, "stone": 10, "metal": 10, "luxury": 5, "research": research}
        allocation["food"] = 100 - sum(allocation.values())
        allocation = {line: allocation[line] for line in sorted(allocation)}
        if allocation != brief["allocation"]:
            add({"kind": "allocate_workers", "allocation": allocation})

        # The outpost meant to become a town: the one with the most open farmland round it.
        if "town" not in memory:
            def farmland(settlement: dict) -> int:
                x, y = parse_tile_key(settlement["tile"])
                return sum(1 for tile, code in brief["known"].items() if code == "P"
                           and max(abs(parse_tile_key(tile)[0] - x), abs(parse_tile_key(tile)[1] - y)) <= 4)
            memory["town"] = sorted(outposts, key=lambda s: (-farmland(s), s["id"]))[0]["id"]
        town = next(s for s in settlements if s["id"] == memory["town"])

        queue = brief["build_queue"]
        # A build that can't be paid for yet waits in the queue; it mustn't stop the same
        # settlement queuing something else behind it.
        queued = {(entry["settlement"], entry["building"]) for entry in queue}
        busy: set[str] = set()  # settlements given a new build this turn
        room = [config.build_queue_max - len(queue)]

        def want(settlement_id: str, building: str, tile: str = "") -> None:
            if room[0] <= 0 or settlement_id in busy or (settlement_id, building) in queued:
                return
            action = {"kind": "build", "settlement": settlement_id, "building": building}
            if tile:
                action["tile"] = tile
            if add(action, f"{settlement_id}:{building}"):
                busy.add(settlement_id)
                room[0] -= 1

        held = set(brief["techs"])
        if "writing" in held and not count(capital, "library"):
            want(capital["id"], "library")
        if "writing" in held and count(capital, "library") and not count(town, "library"):
            want(town["id"], "library")
        if balance(2) >= 0 or stocks["timber"] >= HOUSING_TIMBER:  # no new homes while fuel runs down and is low
            for settlement in outposts + [capital]:  # housing first, outposts before the capital
                if settlement["pop"] >= count(settlement, "housing") * config.housing_capacity - 2:
                    want(settlement["id"], "housing")
        if balance(1) < 0:  # a new farm goes where the most people have no work slot
            def spare_hands(settlement: dict) -> int:
                return settlement["pop"] - sum(config.slots[b] for b in FIELD_WORK for _ in range(count(settlement, b)))
            # shortcut: stops at the first free settlement even if its farm is blocked; trying the next one
            # instead shifts the tuned run-outs (docs/debug-log.md).
            for settlement in sorted(settlements, key=lambda s: (-spare_hands(s), s["id"])):
                if settlement["id"] not in busy:
                    want(settlement["id"], "farm")
                    break
        for column, kind in ((3, "stone"), (4, "metal")):  # a falling stock gets a mine on a free node
            if balance(column) < 0:
                node = next((n for n in brief["nodes"] if n["kind"] == kind and not n["worked"] and n["left"] > 0),
                            None)
                if node:
                    want(node["settlement"], "mine", node["tile"])
        if balance(2) < 0:
            forest = next((n for n in brief["nodes"] if n["kind"] == "forest" and not n["worked"] and n["left"] > 0),
                          None)
            if forest:
                want(forest["settlement"], "lumber_camp", forest["tile"])

        moves, retry = _scout_moves(brief, memory)
        for move in moves:
            add(move)

        memory["blocked"] = dict(sorted(blocked.items()))
        memory["sent"] = sent
        triggers = ["build_done", "tech_unlocked", "unit_arrived", "unit_idle"]
        return {"actions": actions, "end_turn": {"next_wake": {"ticks": 1 if retry else 2, "triggers": triggers}},
                "memory": memory}

    return decide
