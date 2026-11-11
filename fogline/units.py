"""Units: scouts and armies on the map (docs/rules.md section 6).

This module is the only writer of state["units"]. A unit's people are a ledger stock owned by
the unit id, so they stay conserved: spawn moves them out of a settlement (TRAINED), discharge
moves them back (DISBANDED), and nothing else touches them.
"""

import heapq

from fogline import ledger
from fogline.config import Config
from fogline.intmath import PER_MILLE
from fogline.paths import NEIGHBOURS, enter_cost, in_bounds
from fogline.state import parse_tile_key, record_event, tile_key

Log = list[dict] | None


def of_civ(state: dict, civ_id: str) -> list[str]:
    return sorted(uid for uid, unit in state["units"].items() if unit["civ"] == civ_id)


def people(state: dict, civ_id: str) -> int:
    """People serving in a civ's units (they count towards score, not towards eating)."""
    return sum(state["units"][uid]["pop"] for uid in of_civ(state, civ_id))


def is_ready(state: dict, unit: dict) -> bool:
    return state["tick"] >= unit["ready_tick"]


def move_points(config: Config, state: dict, unit: dict) -> int:
    if unit["kind"] == "scout" and "pathfinding" in state["civs"][unit["civ"]]["techs"]:
        return config.scout_move_pathfinding
    return config.units[unit["kind"]]["move"]


def sight_radius(config: Config, state: dict, unit: dict) -> int:
    if unit["kind"] == "scout" and "pathfinding" in state["civs"][unit["civ"]]["techs"]:
        return config.scout_sight_pathfinding
    return config.units[unit["kind"]]["sight"]


def spawn(config: Config, state: dict, civ_id: str, kind: str, settlement_id: str, log: Log, *,
          pay: bool = True, ready_now: bool = False, at: str | None = None) -> str:
    """Create a unit and return its id. Callers check the rules first (actions.train_unit does).

    pay=False and ready_now=True are for the starting scout; `at` places a unit for tests.
    """
    now = state["tick"]
    spec = config.units[kind]
    civ = state["civs"][civ_id]
    settlement = state["settlements"][settlement_id]
    unit_id = f"{civ_id}-u{civ['next_unit']}"
    civ["next_unit"] += 1
    if pay:
        for resource, amount in sorted(spec["cost"].items()):
            ledger.apply(civ["stocks"], state["ledger"], log, civ_id, resource, -amount, ledger.Rule.TRAIN_COST, now)
    unit = {"civ": civ_id, "kind": kind, "home": settlement_id, "tile": at or settlement["tile"], "pop": 0,
            "ready_tick": now if ready_now else now + spec["train_ticks"], "path": [], "target": "",
            "idle_since": now if ready_now else -1}
    state["units"][unit_id] = unit
    ledger.apply(settlement, state["ledger"], log, settlement_id, "pop", -spec["pop"], ledger.Rule.TRAINED, now)
    ledger.apply(unit, state["ledger"], log, unit_id, "pop", spec["pop"], ledger.Rule.TRAINED, now)
    record_event(state, now, "trained", civ_id, f"{kind} {unit_id}")
    return unit_id


def discharge(state: dict, unit_id: str, log: Log, reason: str = "disbanded") -> None:
    """Send a unit's people home and remove it. Its ledger owner then nets to 0."""
    now = state["tick"]
    unit = state["units"][unit_id]
    home = state["settlements"][unit["home"]]
    count = unit["pop"]
    ledger.apply(unit, state["ledger"], log, unit_id, "pop", -count, ledger.Rule.DISBANDED, now)
    ledger.apply(home, state["ledger"], log, unit["home"], "pop", count, ledger.Rule.DISBANDED, now)
    del state["units"][unit_id]
    record_event(state, now, reason, unit["civ"], unit_id)


def route(config: Config, state: dict, start: str, target: str) -> list[str] | None:
    """Cheapest path from start to target as the tiles after start, or None if there is none.

    A* over the true map. Ties break on (cost, estimate, y, x), so every machine walks the
    same path.
    """
    world_map = state["map"]
    tx, ty = parse_tile_key(target)
    if not in_bounds(world_map, tx, ty) or enter_cost(config, world_map, tx, ty) is None:
        return None
    sx, sy = parse_tile_key(start)
    best = {(sx, sy): 0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    queue = [(abs(tx - sx) + abs(ty - sy), 0, sy, sx)]
    while queue:
        _, cost, y, x = heapq.heappop(queue)
        if (x, y) == (tx, ty):
            path = []
            while (x, y) != (sx, sy):
                path.append(tile_key(x, y))
                x, y = came[(x, y)]
            return path[::-1]
        if cost > best[(x, y)]:
            continue
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not in_bounds(world_map, nx, ny):
                continue
            step = enter_cost(config, world_map, nx, ny)
            if step is None:
                continue
            new_cost = cost + step
            if new_cost < best.get((nx, ny), new_cost + 1):
                best[(nx, ny)] = new_cost
                came[(nx, ny)] = (x, y)
                heapq.heappush(queue, (new_cost + abs(tx - nx) + abs(ty - ny), new_cost, ny, nx))
    return None


def order(state: dict, unit_id: str, target: str, path: list[str]) -> None:
    """Give a unit a new destination; an empty path means stay put and go idle."""
    unit = state["units"][unit_id]
    unit["path"] = list(path)
    unit["target"] = target if path else ""
    unit["idle_since"] = -1 if path else state["tick"]


def move_all(config: Config, state: dict, now: int) -> None:
    """Step 4 movement, in unit id order. Points left over at the end of a tick are lost."""
    world_map = state["map"]
    for unit_id in sorted(state["units"]):
        unit = state["units"][unit_id]
        if not is_ready(state, unit):
            continue
        if not unit["path"]:
            if unit["idle_since"] == -1:  # just finished training
                unit["idle_since"] = now
                record_event(state, now, "idle", unit["civ"], unit_id)
            continue
        points = move_points(config, state, unit)
        while unit["path"]:
            step = enter_cost(config, world_map, *parse_tile_key(unit["path"][0]))
            if step is None or step > points:
                break
            points -= step
            unit["tile"] = unit["path"].pop(0)
        if not unit["path"]:
            unit["target"] = ""
            unit["idle_since"] = now
            record_event(state, now, "arrived", unit["civ"], unit_id)


def pay_upkeep(config: Config, state: dict, civ_id: str, log: Log) -> int:
    """Step 6, after eating. Army upkeep grows by 250 per mille for every full 10 army units.

    A unit whose food can't be paid disbands home; its people survive (rules 21). Returns the food
    the units were due, paid or not, which the growth window counts as consumption the way it
    counts people who went unfed (rules 4.1).
    """
    due = 0
    now = state["tick"]
    stocks = state["civs"][civ_id]["stocks"]
    ids = of_civ(state, civ_id)
    armies = sum(1 for uid in ids if config.units[state["units"][uid]["kind"]]["army"])
    scale = PER_MILLE + config.army_upkeep_step * (armies // config.army_upkeep_every)
    # Army upkeep is a running total in per mille, so the scale-up isn't lost to rounding each
    # unit's share down (1 food x 1.25 would otherwise stay 1).
    army_milli = 0
    for unit_id in ids:
        spec = config.units[state["units"][unit_id]["kind"]]
        if spec["army"]:
            before = army_milli
            army_milli += spec["upkeep"] * scale
            food = army_milli // PER_MILLE - before // PER_MILLE
        else:
            food = spec["upkeep"]
        due += food
        if stocks["food"] < food:
            discharge(state, unit_id, log, reason="unit_starved")
            continue
        ledger.apply(stocks, state["ledger"], log, civ_id, "food", -food, ledger.Rule.UNIT_UPKEEP, now)
    return due
