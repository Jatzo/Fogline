"""Sight, the known map and contact (docs/rules.md section 6).

This module is the only writer of civ["known"], civ["met"], civ["in_view"] and civ["sites"].
civ["met"] is the one gate on naming another civ: nothing shows a civ's name or id to a
ruler until it is in there.
"""

from itertools import combinations

from fogline import units
from fogline.config import Config
from fogline.layout import square
from fogline.state import parse_tile_key, record_event, tile_key


def _settlement_radius(config: Config, settlement: dict) -> int:
    fortress = any(b["type"] == "stone_fortress" and not b["ruin"] for b in settlement["buildings"])
    return config.fortress_sight if fortress else config.settlement_sight


def visible(config: Config, state: dict, civ_id: str) -> set[str]:
    """Tiles in sight now: a square round every settlement and unit (rules 21)."""
    size = state["map"]["size"]
    tiles: set[str] = set()
    for settlement in state["settlements"].values():
        if settlement["civ"] == civ_id:
            radius = _settlement_radius(config, settlement)
            tiles.update(tile_key(*t) for t in square(parse_tile_key(settlement["tile"]), radius, size))
    for unit_id in units.of_civ(state, civ_id):
        unit = state["units"][unit_id]
        radius = units.sight_radius(config, state, unit)
        tiles.update(tile_key(*t) for t in square(parse_tile_key(unit["tile"]), radius, size))
    return tiles


def is_known(state: dict, civ_id: str, x: int, y: int) -> bool:
    rows = state["civs"][civ_id]["known"]
    return 0 <= y < len(rows) and 0 <= x < len(rows[y]) and rows[y][x] == "1"


def near_known(state: dict, civ_id: str, tile: str, margin: int) -> bool:
    """True if any tile within margin of this one has been seen (off-map tiles included, so the
    answer never depends on where the edge is)."""
    x, y = parse_tile_key(tile)
    return any(is_known(state, civ_id, x + dx, y + dy)
               for dy in range(-margin, margin + 1) for dx in range(-margin, margin + 1))


def known_tiles(state: dict, civ_id: str) -> list[str]:
    return [tile_key(x, y) for y, row in enumerate(state["civs"][civ_id]["known"])
            for x, char in enumerate(row) if char == "1"]


def update(config: Config, state: dict, now: int) -> None:
    """Step 4, after movement. Every view is worked out before anything is written, then the known
    map, then contact for each unmet pair, then foreign units and settlements in view."""
    civ_ids = sorted(state["civs"])
    views = {civ_id: visible(config, state, civ_id) for civ_id in civ_ids}

    for civ_id in civ_ids:
        rows = [list(row) for row in state["civs"][civ_id]["known"]]
        for tile in views[civ_id]:
            x, y = parse_tile_key(tile)
            rows[y][x] = "1"
        state["civs"][civ_id]["known"] = ["".join(row) for row in rows]

    holdings = {civ_id: set() for civ_id in civ_ids}
    for settlement in state["settlements"].values():
        holdings[settlement["civ"]].add(settlement["tile"])
    for unit in state["units"].values():
        holdings[unit["civ"]].add(unit["tile"])

    for first, second in combinations(civ_ids, 2):
        if second in state["civs"][first]["met"]:
            continue
        if views[first] & holdings[second] or views[second] & holdings[first]:
            state["civs"][first]["met"][second] = now
            state["civs"][second]["met"][first] = now
            record_event(state, now, "contact", first, second)
            record_event(state, now, "contact", second, first)

    for civ_id in civ_ids:
        civ = state["civs"][civ_id]
        in_view = sorted(uid for uid, unit in state["units"].items()
                         if unit["civ"] != civ_id and unit["civ"] in civ["met"] and unit["tile"] in views[civ_id])
        for unit_id in in_view:
            if unit_id not in civ["in_view"]:
                record_event(state, now, "sighted", civ_id, unit_id)
        civ["in_view"] = in_view
        for settlement_id, settlement in sorted(state["settlements"].items()):
            if (settlement["civ"] != civ_id and settlement["civ"] in civ["met"]
                    and settlement["tile"] in views[civ_id]):
                civ["sites"][settlement_id] = {"tile": settlement["tile"], "seen_tick": now}
