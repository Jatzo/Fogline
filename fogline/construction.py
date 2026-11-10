"""Building and growth (docs/rules.md section 15).

Where a building may go, the civ's build queue, and growth stages. The queue runs at the
end of step 7: builds whose settlement is free and whose cost is in stock start and are paid,
then every started build counts down, and finished ones appear on the map.
"""

from fogline import ledger, rules
from fogline.config import Config
from fogline.intmath import per_mille
from fogline.layout import (EDGE_BUILDINGS, EXTRACTION, STAGE_RADIUS, biome_name, claim, core_tile, is_farmland,
                            is_land, node_tiles, occupied_tiles, square)
from fogline.paths import NEIGHBOURS, in_bounds, is_river
from fogline.state import parse_tile_key, record_event as _record, tile_key

NODE_BUILDINGS = {"lumber_camp": ("forest",), "mine": ("stone", "metal")}


def _node_at(state: dict, tile: str) -> dict | None:
    for node in state["nodes"].values():
        if node["tile"] == tile:
            return node
    return None


def _irrigable(state: dict, x: int, y: int) -> bool:
    """Desert on or next to a river, which farms may use with Irrigation."""
    world_map = state["map"]
    if world_map["biome"][y][x] != "D":
        return False
    return is_river(world_map, x, y) or any(
        in_bounds(world_map, x + dx, y + dy) and is_river(world_map, x + dx, y + dy) for dx, dy in NEIGHBOURS)


def terrain_ok(config: Config, state: dict, civ_id: str, building: str, tile: str) -> bool:
    x, y = parse_tile_key(tile)
    world_map = state["map"]
    if not is_land(world_map, x, y):
        return False
    node = _node_at(state, tile)
    if building in NODE_BUILDINGS:
        return node is not None and node["kind"] in NODE_BUILDINGS[building] and node["node"] > 0
    if node is not None:
        return False  # only lumber camps and mines go on nodes
    if building == "farm":
        irrigation = "irrigation" in state["civs"][civ_id]["techs"]
        return is_farmland(world_map, x, y) or (irrigation and _irrigable(state, x, y))
    if building == "pasture":
        return biome_name(world_map, tile) in config.pasture_biomes
    if building == "harbour":
        return biome_name(world_map, tile) == "coast"
    return True


def _in_footprint(settlement: dict, tile: str) -> bool:
    cx, cy = parse_tile_key(settlement["tile"])
    x, y = parse_tile_key(tile)
    return max(abs(x - cx), abs(y - cy)) <= STAGE_RADIUS[settlement["stage"]]


def _claim_owner(config: Config, state: dict, civ_id: str, tile: str) -> str | None:
    """For an unclaimed tile within reach of own land, the nearest own settlement (rules 15.4)."""
    if tile in state["territory"]:
        return None
    x, y = parse_tile_key(tile)
    reach = config.node_claim_reach
    near_own = any(state["settlements"][state["territory"][tile_key(*t)]]["civ"] == civ_id
                   for t in square((x, y), reach, state["map"]["size"]) if tile_key(*t) in state["territory"])
    if not near_own:
        return None
    own = sorted(sid for sid, s in state["settlements"].items() if s["civ"] == civ_id)

    def distance(sid: str) -> int:
        sx, sy = parse_tile_key(state["settlements"][sid]["tile"])
        return (sx - x) ** 2 + (sy - y) ** 2

    return min(own, key=lambda sid: (distance(sid), sid))


def _hint_owner(config: Config, state: dict, settlement_id: str, building: str, hint: str) -> str | None:
    """The settlement a valid tile hint would belong to, or None if the hint can't be used."""
    settlement = state["settlements"][settlement_id]
    civ_id = settlement["civ"]
    try:
        x, y = parse_tile_key(hint)
    except ValueError:
        return None
    if not in_bounds(state["map"], x, y) or hint in occupied_tiles(state):
        return None
    if not terrain_ok(config, state, civ_id, building, hint):
        return None
    owner = state["territory"].get(hint)
    if building in EXTRACTION:
        if owner == settlement_id:
            return owner
        if owner is None and building in NODE_BUILDINGS:
            return _claim_owner(config, state, civ_id, hint)
        return None
    return settlement_id if owner == settlement_id and _in_footprint(settlement, hint) else None


def _nearest_border(state: dict, settlement: dict) -> tuple[int, int] | None:
    civ_id = settlement["civ"]
    centre = parse_tile_key(settlement["tile"])
    for x, y in square(centre, state["map"]["size"], state["map"]["size"]):
        owner = state["territory"].get(tile_key(x, y))
        if owner is None or state["settlements"][owner]["civ"] != civ_id:
            return x, y
    return None


def place(config: Config, state: dict, settlement_id: str, building: str, hint: str | None) -> tuple[str, str] | None:
    """Choose the tile for a new building: the hint if it is valid, else the default layout.

    Returns (tile, owning settlement), or None if nowhere fits.
    """
    if hint:
        owner = _hint_owner(config, state, settlement_id, building, hint)
        if owner is not None:
            return hint, owner
    settlement = state["settlements"][settlement_id]
    civ_id = settlement["civ"]

    def fits(tile: str) -> bool:
        return terrain_ok(config, state, civ_id, building, tile)

    if building not in EXTRACTION:
        border = _nearest_border(state, settlement) if building in EDGE_BUILDINGS else None
        tile = core_tile(state, settlement, building, border, fits)
        return (tile, settlement_id) if tile else None

    taken = occupied_tiles(state)
    nodes = node_tiles(state)
    centre = parse_tile_key(settlement["tile"])
    radius = STAGE_RADIUS[settlement["stage"]] + config.claim_extra_radius
    own = [tile_key(*t) for t in square(centre, radius, state["map"]["size"])
           if state["territory"].get(tile_key(*t)) == settlement_id and tile_key(*t) not in taken]
    own = [t for t in own if fits(t) and (building in NODE_BUILDINGS or t not in nodes)]
    # Fields and pastures go outside the footprint first, keeping the centre for the town.
    own.sort(key=lambda t: _in_footprint(settlement, t))
    return (own[0], settlement_id) if own else None


def queue_cost(config: Config, building: str, mode: str) -> dict[str, int]:
    base = config.buildings[building]["cost"]
    rate = {"new": 1000, "rebuild": config.rebuild_rate, "repair": config.repair_rate}[mode]
    return {res: per_mille(amount, rate) for res, amount in sorted(base.items())}


def queue_ticks(config: Config, building: str, mode: str) -> int:
    return config.repair_ticks if mode == "repair" else config.buildings[building]["ticks"]


def _start(config: Config, state: dict, now: int, civ_id: str, log) -> None:
    civ = state["civs"][civ_id]
    stocks = civ["stocks"]
    busy = {e["settlement"] for e in civ["build_queue"] if e["started"]}
    for entry in civ["build_queue"]:
        if entry["started"] or entry["settlement"] in busy:
            continue
        if any(stocks[res] < amount for res, amount in entry["cost"].items()):
            continue  # waits for stock; other settlements may still start theirs
        if entry["mode"] == "new":
            placed = place(config, state, entry["settlement"], entry["building"], entry["hint"])
            if placed is None:
                entry["dropped"] = True
                _record(state, now, "build_failed", civ_id, f"{entry['building']} at {entry['settlement']}: no_tile")
                continue
            entry["tile"], entry["settlement"] = placed
        for res, amount in entry["cost"].items():
            ledger.apply(stocks, state["ledger"], log, civ_id, res, -amount, ledger.Rule.BUILD_COST, now)
        entry["started"] = True
        busy.add(entry["settlement"])


def _finish(config: Config, state: dict, now: int, entry: dict) -> None:
    settlement = state["settlements"][entry["settlement"]]
    if entry["mode"] == "new":
        settlement["buildings"].append({"type": entry["building"], "tile": entry["tile"], "built_tick": now,
                                        "owed": False, "arrears_ticks": 0, "damaged": False, "ruin": False})
        if entry["tile"] not in state["territory"]:
            x, y = parse_tile_key(entry["tile"])
            for tx, ty in square((x, y), config.node_claim_radius, state["map"]["size"]):
                key = tile_key(tx, ty)
                if is_land(state["map"], tx, ty) and key not in state["territory"]:
                    state["territory"][key] = entry["settlement"]
    else:
        building = next(b for b in settlement["buildings"] if b["tile"] == entry["tile"])
        if entry["mode"] == "rebuild":
            building.update(ruin=False, damaged=False, owed=False, arrears_ticks=0, built_tick=now)
        else:
            building["damaged"] = False
    _record(state, now, "built", settlement["civ"], f"{entry['mode']} {entry['building']} at {entry['tile']}")


def _update_stages(config: Config, state: dict, now: int, civ_id: str) -> None:
    order = config.stage_order
    for settlement_id in sorted(sid for sid, s in state["settlements"].items() if s["civ"] == civ_id):
        settlement = state["settlements"][settlement_id]
        standing = [b["type"] for b in settlement["buildings"] if not b["ruin"]]
        target = rules.stage_for(config, settlement["pop"], standing)
        current = settlement["stage"]
        if order.index(target) > order.index(current):
            settlement["stage"] = target
            settlement["below_band_ticks"] = 0
            claim(state, settlement_id, config.claim_extra_radius)
            _record(state, now, "stage", civ_id, f"{settlement_id} {current} to {target}")
        elif settlement["pop"] < config.stage_min_pop[current]:
            settlement["below_band_ticks"] += 1
            if settlement["below_band_ticks"] >= config.stage_drop_ticks:
                lower = order[order.index(current) - 1]
                settlement["stage"] = lower  # claimed land is kept
                settlement["below_band_ticks"] = 0
                _record(state, now, "stage", civ_id, f"{settlement_id} {current} to {lower}")
        else:
            settlement["below_band_ticks"] = 0


def advance(config: Config, state: dict, now: int, civ_id: str, log) -> None:
    """Start what can start, count down what is building, finish what is done, then update stages."""
    civ = state["civs"][civ_id]
    _start(config, state, now, civ_id, log)
    remaining = []
    for entry in civ["build_queue"]:
        if entry["dropped"]:
            continue
        if entry["started"]:
            entry["ticks_left"] -= 1
            if entry["ticks_left"] == 0:
                _finish(config, state, now, entry)
                continue
        remaining.append(entry)
    civ["build_queue"] = remaining
    _update_stages(config, state, now, civ_id)
