"""Where buildings go and which tiles a settlement claims (docs/rules.md section 15)."""

from fogline.paths import BIOME_CODES, is_river
from fogline.state import tile_key

EXTRACTION = frozenset({"farm", "lumber_camp", "mine", "pasture"})
CENTRE_BUILDINGS = frozenset({"market", "library", "printing_house"})
EDGE_BUILDINGS = frozenset({"barracks", "town_walls"})

STAGE_RADIUS = {"hamlet": 1, "village": 2, "town": 3, "city": 4}


def square(centre: tuple[int, int], radius: int, size: int) -> list[tuple[int, int]]:
    """Tiles within Chebyshev radius, nearest the centre first, ties by row then column."""
    cx, cy = centre
    tiles = [
        (x, y)
        for y in range(max(0, cy - radius), min(size, cy + radius + 1))
        for x in range(max(0, cx - radius), min(size, cx + radius + 1))
    ]
    return sorted(tiles, key=lambda t: ((t[0] - cx) ** 2 + (t[1] - cy) ** 2, t[1], t[0]))


def is_land(world_map: dict, x: int, y: int) -> bool:
    return world_map["biome"][y][x] != "S"


def is_farmland(world_map: dict, x: int, y: int) -> bool:
    code = world_map["biome"][y][x]
    if code == "P":
        return True
    return is_river(world_map, x, y) and code not in ("M", "S")


def occupied_tiles(state: dict) -> set[str]:
    taken = {b["tile"] for s in state["settlements"].values() for b in s["buildings"]}
    taken.update(s["tile"] for s in state["settlements"].values())
    # A build that has started holds its tile until it is finished.
    taken.update(e["tile"] for c in state["civs"].values() for e in c["build_queue"] if e["tile"])
    return taken


def node_tiles(state: dict) -> set[str]:
    return {n["tile"] for n in state["nodes"].values()}


def core_tile(state: dict, settlement: dict, building: str, nearest_border: tuple[int, int] | None,
              fits=None) -> str | None:
    """Default layout for a non-extraction building inside the footprint.

    Centre buildings take the free tile nearest the centre; edge buildings take the free
    footprint-edge tile nearest the border; everything else fills from the centre out.
    """
    world_map = state["map"]
    cx, cy = (int(v) for v in settlement["tile"].split(","))
    radius = STAGE_RADIUS[settlement["stage"]]
    taken = occupied_tiles(state) | node_tiles(state)
    candidates = [
        (x, y) for x, y in square((cx, cy), radius, world_map["size"])
        if is_land(world_map, x, y) and tile_key(x, y) not in taken and (fits is None or fits(tile_key(x, y)))
    ]
    if not candidates:
        return None
    if building in EDGE_BUILDINGS and nearest_border is not None:
        edge = [t for t in candidates if max(abs(t[0] - cx), abs(t[1] - cy)) == radius] or candidates
        bx, by = nearest_border
        edge.sort(key=lambda t: ((t[0] - bx) ** 2 + (t[1] - by) ** 2, t[1], t[0]))
        return tile_key(*edge[0])
    return tile_key(*candidates[0])


def farm_tile(state: dict, settlement_id: str) -> str | None:
    """Nearest free farmland tile in the settlement's own territory, outside its footprint first."""
    settlement = state["settlements"][settlement_id]
    world_map = state["map"]
    cx, cy = (int(v) for v in settlement["tile"].split(","))
    radius = STAGE_RADIUS[settlement["stage"]]
    taken = occupied_tiles(state) | node_tiles(state)
    own = [
        (x, y) for x, y in square((cx, cy), radius + 3, world_map["size"])
        if state["territory"].get(tile_key(x, y)) == settlement_id
        and tile_key(x, y) not in taken and is_farmland(world_map, x, y)
    ]
    outside = [t for t in own if max(abs(t[0] - cx), abs(t[1] - cy)) > radius]
    pick = outside or own
    return tile_key(*pick[0]) if pick else None


def claim(state: dict, settlement_id: str, extra_radius: int) -> None:
    """Claim unclaimed tiles within footprint radius + 3. Older claims keep their tiles."""
    settlement = state["settlements"][settlement_id]
    cx, cy = (int(v) for v in settlement["tile"].split(","))
    radius = STAGE_RADIUS[settlement["stage"]] + extra_radius
    world_map = state["map"]
    for x, y in square((cx, cy), radius, world_map["size"]):
        key = tile_key(x, y)
        if is_land(world_map, x, y) and key not in state["territory"]:
            state["territory"][key] = settlement_id


def biome_name(world_map: dict, tile: str) -> str:
    x, y = (int(v) for v in tile.split(","))
    return BIOME_CODES[world_map["biome"][y][x]]
