"""Seeded world generation (docs/rules.md section 2, plan fix 7).

Capitals are placed first, on a pentagon with jitter, so spacing is designed rather than
hoped for. Home regions are painted around them, the rest is filled from integer value
noise, then nodes, settlements, starting buildings and town traits are added. Every draw
uses the worldgen stream with its own purpose key, and every stock is created through the
ledger under the WORLDGEN rule.
"""

from math import isqrt

from fogline import layout, ledger, memory, reputation, rng, sight, units
from fogline.config import Config
from fogline.paths import CODE_FOR, path_costs
from fogline.state import tile_key

# Pentagon unit vectors (x, y) times 1000, y pointing south. Slot 0 is north.
PENTAGON = ((0, -1000), (951, -309), (588, 809), (-588, 809), (-951, -309))

STARTING_TECHS = ("farming", "simple_tools", "huts", "basic_crafts")
LINES = ("food", "timber", "stone", "metal")
QUIRKS = (
    "famed_smith", "fragile_harbour", "plague_prone_slum", "lucky_harvests", "quarrelsome_guilds",
    "old_shrine", "rich_seam", "flood_meadow", "proud_militia", "busy_crossroads", "lean_winters", "storytellers",
)
SETTLEMENT_NAMES = {
    "ironhold": ("Karrak Deep", "Greyspur", "Anvilmouth", "Cold Hearth"),
    "verdance": ("Greenmere", "Thornwick", "Mossford", "Elderglade"),
    "saltreach": ("Brinehaven", "Gullstone", "Tidewatch", "Shellcove"),
    "dunerunners": ("Sand Gate", "Red Wells", "Ashwind", "Mirage Rest"),
    "frostmark": ("Hrimvald", "Winterholt", "Pale Ford", "Snowmantle"),
}
HOME_PATCH = {  # inside a home region, noise below the threshold gives the second biome
    "mountains": (300, "plains", "mountains"),
    "forest": (400, "plains", "forest"),
    "desert": (200, "plains", "desert"),
    "tundra": (250, "forest", "tundra"),
    "coast": (450, "plains", "coast"),
}
NODE_BIOMES = {"forest": ("forest",), "stone": ("mountains", "desert", "coast"),
               "metal": ("mountains", "desert", "tundra")}
NODE_FALLBACK = {"forest": "forest", "stone": "mountains", "metal": "mountains"}
RESOURCE_NODE = {"timber": "forest", "stone": "stone", "metal": "metal"}


class WorldgenError(RuntimeError):
    """Raised when no attempt produced a world that meets the spacing rules."""


class _Reroll(Exception):
    """An attempt that can't meet a placement rule; generate() moves to the next attempt."""


def generate(config: Config, seed: int) -> dict:
    """Build the tick-0 state for a seed, re-rolling deterministically until spacing holds."""
    for attempt in range(config.worldgen_attempts):
        try:
            state = _build(config, seed, attempt)
        except _Reroll:
            continue
        if _spacing_ok(config, state):
            sight.update(config, state, 0, seen_from=0)  # land round its towns, and any neighbour, known at turn 0
            return state
    raise WorldgenError(f"seed {seed}: no world met the spacing rules in {config.worldgen_attempts} attempts")


def capital_path_costs(config: Config, state: dict) -> dict[tuple[str, str], int | None]:
    """Movement-point cost between every pair of capitals (None if unreachable)."""
    capitals = {civ: _xy(state["settlements"][f"{civ}-0"]["tile"]) for civ in state["civs"]}
    result: dict[tuple[str, str], int | None] = {}
    for civ, start in sorted(capitals.items()):
        costs = path_costs(config, state["map"], start)
        for other, end in sorted(capitals.items()):
            if other > civ:
                result[(civ, other)] = costs.get(end)
    return result


def _spacing_ok(config: Config, state: dict) -> bool:
    costs = capital_path_costs(config, state)
    return all(cost is not None and cost >= config.min_capital_path_cost for cost in costs.values())


def _xy(tile: str) -> tuple[int, int]:
    x, y = tile.split(",")
    return int(x), int(y)


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _draw(seed: int, attempt: int, purpose: str, civ: str = rng.WORLD):
    return rng.stream(seed, "worldgen", attempt, civ, purpose)


def _noise(seed: int, attempt: int, size: int, spacing: int, purpose: str):
    """Integer value noise in 0..999, bilinear between lattice points."""
    draw = _draw(seed, attempt, f"noise-{purpose}")
    cells = size // spacing + 2
    lattice = [[draw.randrange(1000) for _ in range(cells)] for _ in range(cells)]

    def at(x: int, y: int) -> int:
        gx, fx = divmod(x, spacing)
        gy, fy = divmod(y, spacing)
        top = lattice[gy][gx] * (spacing - fx) + lattice[gy][gx + 1] * fx
        bottom = lattice[gy + 1][gx] * (spacing - fx) + lattice[gy + 1][gx + 1] * fx
        return (top * (spacing - fy) + bottom * fy) // (spacing * spacing)

    return at


def _build(config: Config, seed: int, attempt: int) -> dict:
    # The land is drawn on its own grid first, then set inside the sea border, so the border
    # adds ocean round the world rather than drowning anyone's home land.
    size = config.map_size - 2 * config.sea_border
    centre = (size // 2, size // 2)
    civ_ids = [spec.civ_id for spec in config.civs]

    # Capitals: Frostmark takes the north slot; the others are shuffled into the rest.
    others = [c for c in civ_ids if c != "frostmark"]
    _draw(seed, attempt, "slots").shuffle(others)
    if config.slice_pair:  # the slice pair takes slots 1 and 2, neighbours on the ring (the draw still runs)
        others = list(config.slice_pair) + [c for c in others if c not in config.slice_pair]
    slot_civs = ["frostmark", *others]
    jitter = _draw(seed, attempt, "jitter")
    capitals: dict[str, tuple[int, int]] = {}
    low, high = config.edge_margin, size - 1 - config.edge_margin
    for slot, civ in enumerate(slot_civs):
        ux, uy = PENTAGON[slot]
        x = centre[0] + config.capital_ring_radius * ux // 1000 + jitter.randint(-config.capital_jitter, config.capital_jitter)
        y = centre[1] + config.capital_ring_radius * uy // 1000 + jitter.randint(-config.capital_jitter, config.capital_jitter)
        capitals[civ] = (min(max(x, low), high), min(max(y, low), high))

    biome = _paint_biomes(config, seed, attempt, capitals, centre, size)
    river = [["0"] * size for _ in range(size)]
    for civ in civ_ids:
        if config.civ(civ).home_biome in ("forest", "desert"):
            _draw_river(seed, attempt, civ, centre, capitals[civ], river)
    border = config.sea_border
    biome = _coast(_pad(biome, border, "S"))
    river = _pad(river, border, "0")
    capitals = {civ: (x + border, y + border) for civ, (x, y) in capitals.items()}
    size = config.map_size

    state = {
        "version": 1,
        "seed": seed,
        "worldgen_attempt": attempt,
        "tick": 0,
        "config_hash": config.config_hash(),
        "map": {"size": size, "biome": ["".join(row) for row in biome], "river": ["".join(row) for row in river],
                "passes": {}, "tracks": []},
        "civs": {},
        "settlements": {},
        "nodes": {},
        "territory": {},
        "ledger": {},
        "world": {"harsh_winter_tick": -1},
        "events": [],
        "units": {},
        "reputation": reputation.initial(config, civ_ids),
        "couriers": [],
        "offers": {},
        "next_offer": 0,
        "prices": {},
    }

    for civ in civ_ids:
        _ensure_farmland(config, state, capitals[civ])
    for civ in civ_ids:
        _home_nodes(config, state, seed, attempt, civ, capitals[civ])
    for civ in civ_ids:
        _found_civ(config, state, seed, attempt, civ, capitals)
    if config.slice_pair:
        _meet_scouts(state, config.slice_pair, capitals)
    # After founding, so no outpost's claim can swallow a node meant to belong to nobody.
    _contestable_nodes(config, state, seed, attempt, capitals)
    return state


def _land_near(state: dict, target: tuple[int, int], taken: set[tuple[int, int]]) -> tuple[int, int]:
    """The land tile nearest target (Chebyshev rings, then y and x), not in taken."""
    size = state["map"]["size"]
    for radius in range(size):
        ring = sorted((y, x) for y in range(target[1] - radius, target[1] + radius + 1)
                      for x in range(target[0] - radius, target[0] + radius + 1)
                      if max(abs(x - target[0]), abs(y - target[1])) == radius and 0 <= x < size and 0 <= y < size)
        for y, x in ring:
            if layout.is_land(state["map"], x, y) and (x, y) not in taken:
                return x, y
    raise _Reroll("no land for the slice scouts")


def _meet_scouts(state: dict, pair: tuple[str, ...], capitals: dict[str, tuple[int, int]]) -> None:
    """Set the slice pair's starting scouts down side by side halfway between their capitals, in
    each other's sight, so the two civs meet in the first ticks whatever their rulers do."""
    a, b = pair
    middle = ((capitals[a][0] + capitals[b][0]) // 2, (capitals[a][1] + capitals[b][1]) // 2)
    first = _land_near(state, middle, set())
    second = _land_near(state, first, {first})
    state["units"][f"{a}-u0"]["tile"] = tile_key(*first)
    state["units"][f"{b}-u0"]["tile"] = tile_key(*second)


def _paint_biomes(config: Config, seed: int, attempt: int, capitals: dict[str, tuple[int, int]],
                  centre: tuple[int, int], size: int) -> list[list[str]]:
    noise = _noise(seed, attempt, size, config.noise_spacing, "biome")
    order = list(capitals)
    grid = [["P"] * size for _ in range(size)]
    home2 = config.home_radius ** 2
    for y in range(size):
        for x in range(size):
            owner = min(order, key=lambda c: (_dist2((x, y), capitals[c]), order.index(c)))
            spec = config.civ(owner)
            value = noise(x, y)
            if spec.home_biome == "coast":
                beyond = isqrt(_dist2((x, y), centre)) >= isqrt(_dist2(capitals[owner], centre)) + 3
                if beyond:
                    grid[y][x] = "S"
                    continue
            if _dist2((x, y), capitals[owner]) <= home2:
                threshold, low_biome, high_biome = HOME_PATCH[spec.home_biome]
                name = low_biome if value < threshold else high_biome
            # Thresholds are the measured 40th and 75th percentiles of the noise, so the open
            # land is about 40% plains, 35% forest and 25% mountains.
            elif value < 446:
                name = "plains"
            elif value < 637:
                name = "forest"
            else:
                name = "mountains"
            grid[y][x] = CODE_FOR[name]
    return _coast(grid)


def _pad(grid: list[list[str]], border: int, fill: str) -> list[list[str]]:
    width = len(grid) + 2 * border
    rows = [[fill] * width for _ in range(border)]
    rows += [[fill] * border + row + [fill] * border for row in grid]
    return rows + [[fill] * width for _ in range(border)]


def _coast(grid: list[list[str]]) -> list[list[str]]:
    """Land touching the sea is coast."""
    size = len(grid)
    for y in range(size):
        for x in range(size):
            if grid[y][x] != "S" and any(
                0 <= x + dx < size and 0 <= y + dy < size and grid[y + dy][x + dx] == "S"
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                grid[y][x] = "C"
    return grid


def _draw_river(seed: int, attempt: int, civ: str, start: tuple[int, int], end: tuple[int, int],
                river: list[list[str]]) -> None:
    """A wandering river from the map centre down to a capital's door."""
    draw = _draw(seed, attempt, "river", civ)
    x, y = start
    while (x, y) != end:
        dx = (end[0] > x) - (end[0] < x)
        dy = (end[1] > y) - (end[1] < y)
        if dx and dy:
            if draw.randrange(2):
                dy = 0
            else:
                dx = 0
        x, y = x + dx, y + dy
        if (x, y) != end:
            river[y][x] = "1"


def _set_biome(state: dict, x: int, y: int, name: str) -> None:
    row = state["map"]["biome"][y]
    state["map"]["biome"][y] = row[:x] + CODE_FOR[name] + row[x + 1:]


def _ensure_farmland(config: Config, state: dict, capital: tuple[int, int]) -> None:
    """Guarantee enough farmland near each capital for its starting farms."""
    world_map = state["map"]
    ring = [t for t in layout.square(capital, config.home_node_ring_max, world_map["size"])
            if 2 <= max(abs(t[0] - capital[0]), abs(t[1] - capital[1])) and layout.is_land(world_map, *t)]
    have = sum(1 for t in ring if layout.is_farmland(world_map, *t))
    # Inland tiles first; coast is turned to farmland only when nothing else is left.
    for allow_coast in (False, True):
        for x, y in ring:
            if have >= config.capital_farmland_min:
                return
            code = world_map["biome"][y][x]
            if not layout.is_farmland(world_map, x, y) and (allow_coast or code != "C"):
                _set_biome(state, x, y, "plains")
                have += 1


def add_node(state: dict, node_id: str, kind: str, tile: str, size: int, regrowth: int, home: str,
             small: bool, rule: ledger.Rule = ledger.Rule.WORLDGEN, tick: int = 0,
             log: list | None = None) -> None:
    node = {"kind": kind, "tile": tile, "size": size, "regrowth": regrowth, "home": home, "small": small,
            "finite": kind != "luxury", "node": 0}
    state["nodes"][node_id] = node
    if node["finite"]:
        ledger.apply(node, state["ledger"], log, node_id, "node", size, rule, tick)


def _pick_node_tile(state: dict, draw, kind: str, centre: tuple[int, int], ring_min: int, ring_max: int) -> str:
    world_map = state["map"]
    taken = {n["tile"] for n in state["nodes"].values()}
    ring = [t for t in layout.square(centre, ring_max, world_map["size"])
            if ring_min <= max(abs(t[0] - centre[0]), abs(t[1] - centre[1]))
            and layout.is_land(world_map, *t) and tile_key(*t) not in taken]
    if kind == "luxury":
        return tile_key(*ring[draw.randrange(len(ring))])
    suitable = [t for t in ring if layout.biome_name(world_map, tile_key(*t)) in NODE_BIOMES[kind]]
    if suitable:
        return tile_key(*suitable[draw.randrange(len(suitable))])
    x, y = ring[draw.randrange(len(ring))]
    _set_biome(state, x, y, NODE_FALLBACK[kind])
    return tile_key(x, y)


def _home_nodes(config: Config, state: dict, seed: int, attempt: int, civ: str, capital: tuple[int, int]) -> None:
    spec = config.civ(civ)
    draw = _draw(seed, attempt, "home-nodes", civ)
    full_size = {"forest": config.forest_node_size, "stone": config.stone_node_size, "metal": config.metal_node_size}
    small_size = {"forest": config.short_forest_size, "stone": config.short_stone_size, "metal": config.short_metal_size}
    count = 0
    for resource in ("timber", "stone", "metal"):
        kind = RESOURCE_NODE[resource]
        if resource in spec.rich_in:
            plan = [False, False]
        elif resource in spec.short_of:
            plan = [True]
        else:
            plan = [False]
        for small in plan:
            tile = _pick_node_tile(state, draw, kind, capital, config.home_node_ring_min, config.home_node_ring_max)
            size = small_size[kind] if small else full_size[kind]
            if kind == "forest":
                regrowth = config.short_forest_regrowth if small else config.forest_regrowth
            else:
                regrowth = 0
            add_node(state, f"{civ}-n{count}", kind, tile, size, regrowth, civ, small)
            count += 1
    tile = _pick_node_tile(state, draw, "luxury", capital, 1, 3)
    add_node(state, f"{civ}-lux", "luxury", tile, 0, 0, civ, False)


def _contestable_nodes(config: Config, state: dict, seed: int, attempt: int,
                       capitals: dict[str, tuple[int, int]]) -> None:
    """Nodes in the gaps between home regions, about equally far from two capitals."""
    world_map = state["map"]
    costs = {civ: path_costs(config, world_map, pos) for civ, pos in sorted(capitals.items())}
    home2 = config.home_radius ** 2
    taken = {n["tile"] for n in state["nodes"].values()}
    candidates = []
    for y in range(world_map["size"]):
        for x in range(world_map["size"]):
            if not layout.is_land(world_map, x, y) or tile_key(x, y) in taken or tile_key(x, y) in state["territory"]:
                continue
            if any(_dist2((x, y), pos) <= home2 for pos in capitals.values()):
                continue
            reach = sorted(c[(x, y)] for c in costs.values() if (x, y) in c)
            if len(reach) >= 2 and reach[1] - reach[0] <= config.contestable_cost_gap:
                candidates.append((x, y))
    draw = _draw(seed, attempt, "contestable")
    draw.shuffle(candidates)
    wanted = draw.randint(config.contestable_nodes_min, config.contestable_nodes_max)
    chosen: list[tuple[int, int]] = []
    for tile in candidates:
        if all(max(abs(tile[0] - c[0]), abs(tile[1] - c[1])) >= config.contestable_min_spacing for c in chosen):
            chosen.append(tile)
        if len(chosen) == wanted:
            break
    if len(chosen) < config.contestable_nodes_min:
        raise _Reroll(f"only {len(chosen)} contestable nodes fit")
    sizes = {"forest": config.forest_node_size, "stone": config.stone_node_size, "metal": config.metal_node_size}
    for index, (x, y) in enumerate(chosen):
        kind = ("forest", "stone", "metal")[draw.randrange(3)]
        if layout.biome_name(world_map, tile_key(x, y)) not in NODE_BIOMES[kind]:
            _set_biome(state, x, y, NODE_FALLBACK[kind])
        regrowth = config.forest_regrowth if kind == "forest" else 0
        add_node(state, f"contest-{index}", kind, tile_key(x, y), sizes[kind], regrowth, "", False)


def _new_settlement(config: Config, state: dict, civ: str, index: int, tile: str, pop: int, stage: str,
                    name: str) -> str:
    settlement_id = f"{civ}-{index}"
    settlement = {"civ": civ, "name": name, "tile": tile, "stage": stage, "capital": index == 0,
                  "buildings": [], "pop": 0, "growth_acc": 0, "specialty": {}, "need": "", "quirk": "",
                  "founded_tick": 0, "workers": {}, "idle_until": -1, "modifiers": [],
                  "below_band_ticks": 0}
    state["settlements"][settlement_id] = settlement
    ledger.apply(settlement, state["ledger"], None, settlement_id, "pop", pop, ledger.Rule.WORLDGEN, 0)
    layout.claim(state, settlement_id, config.claim_extra_radius)
    return settlement_id


def _build_on(state: dict, settlement_id: str, building: str, tile: str | None) -> None:
    if tile is None:
        raise RuntimeError(f"no tile for starting {building} in {settlement_id}")
    state["settlements"][settlement_id]["buildings"].append({
        "type": building, "tile": tile, "built_tick": 0,
        "owed": False, "arrears_ticks": 0, "damaged": False, "ruin": False})


def _node_for(state: dict, settlement_id: str, kinds: tuple[str, ...], allow_small: bool) -> str | None:
    """Nearest home node of the given kinds inside this settlement's territory."""
    settlement = state["settlements"][settlement_id]
    centre = _xy(settlement["tile"])
    options = [
        n for n in state["nodes"].values()
        if n["kind"] in kinds and state["territory"].get(n["tile"]) == settlement_id
        and (allow_small or not n["small"])
    ]
    options.sort(key=lambda n: (_dist2(_xy(n["tile"]), centre), n["tile"]))
    return options[0]["tile"] if options else None


def _found_civ(config: Config, state: dict, seed: int, attempt: int, civ: str,
               capitals: dict[str, tuple[int, int]]) -> None:
    spec = config.civ(civ)
    names = SETTLEMENT_NAMES[civ]
    civ_state = {
        "stocks": {},
        "stability": config.stability_start,
        "techs": list(STARTING_TECHS),
        "research": {"tech": "", "points_milli": 0},
        "food_worker_cap": config.short_food_worker_cap if "food" in spec.short_of else 0,
        "temperament": {"generosity": spec.generosity, "ruthlessness": spec.ruthlessness,
                        "insularity": spec.insularity},
        "bot_memory": {},
        "memory": memory.empty(),
        "inbox": [],
        "allocation": dict(config.default_allocation),
        "tools_short": False,
        "food_window": [],
        "low_stability_ticks": 0,
        "luxury_used_tick": -1,
        "luxury_consumed": 0,
        "shock": 0,
        "target_mods": [],
        "modifiers": [],
        "score": 0,
        "prestige": 0,
        "build_queue": [],
        "turn": {"wake_at": 0, "last_woke": 0, "triggers": [], "cursor": 0, "rejections": [],
                 "invalid_streak": 0, "skip_next": False, "below": [], "seen_stocks": {}},
        "origin": "",
        "known": ["0" * config.map_size for _ in range(config.map_size)],
        "met": {},
        "first_contact_turn": None,  # the first tick whose turn could see a met civ
        "in_view": [],
        "sites": {},
        "reorders": [],
        "next_unit": 0,
    }
    state["civs"][civ] = civ_state
    for resource, amount in sorted(spec.start_stock.items()):
        ledger.apply(civ_state["stocks"], state["ledger"], None, civ, resource, amount, ledger.Rule.WORLDGEN, 0)

    capital = capitals[civ]
    capital_id = _new_settlement(config, state, civ, 0, tile_key(*capital), config.starting_capital_pop, "village", names[0])
    for _ in range(5):
        _build_on(state, capital_id, "housing", layout.core_tile(state, state["settlements"][capital_id], "housing", None))
    for _ in range(4):
        _build_on(state, capital_id, "farm", layout.farm_tile(state, capital_id))
    _build_on(state, capital_id, "lumber_camp", _node_for(state, capital_id, ("forest",), allow_small=True))
    _build_on(state, capital_id, "mine", _node_for(state, capital_id, ("stone", "metal"), allow_small=False))
    _build_on(state, capital_id, "workshop", layout.core_tile(state, state["settlements"][capital_id], "workshop", None))

    # Outposts face away from the nearest other capital.
    nearest = min((c for c in capitals if c != civ), key=lambda c: (_dist2(capital, capitals[c]), c))
    away = (capital[0] - capitals[nearest][0], capital[1] - capitals[nearest][1])
    world_map = state["map"]
    taken = layout.occupied_tiles(state) | layout.node_tiles(state)
    ring = [
        t for t in layout.square(capital, config.outpost_distance_max, world_map["size"])
        if max(abs(t[0] - capital[0]), abs(t[1] - capital[1])) >= config.outpost_distance_min
        and _dist2(t, capital) <= config.outpost_distance_max ** 2
        and layout.is_land(world_map, *t) and tile_key(*t) not in taken
        and tile_key(*t) not in state["territory"]
    ]
    draw = _draw(seed, attempt, "outposts", civ)
    draw.shuffle(ring)
    facing_away = [t for t in ring if (t[0] - capital[0]) * away[0] + (t[1] - capital[1]) * away[1] > 0]
    # Away from the neighbour first; a coast with sea on the far side falls back to any side.
    # Outposts are placed one at a time so each sees the land the earlier ones claimed.
    chosen: list[tuple[int, int]] = []
    for tile in facing_away + [t for t in ring if t not in facing_away]:
        if len(chosen) == config.outposts_per_civ:
            break
        if any(max(abs(tile[0] - c[0]), abs(tile[1] - c[1])) < config.outpost_min_spacing for c in chosen):
            continue
        busy = layout.occupied_tiles(state) | layout.node_tiles(state)
        free = [t for t in layout.square(tile, 2, world_map["size"])
                if t != tile and layout.is_land(world_map, *t)
                and tile_key(*t) not in state["territory"] and tile_key(*t) not in busy]
        if tile_key(*tile) in state["territory"] or len(free) < 4:
            continue
        chosen.append(tile)
        index = len(chosen)
        outpost_id = _new_settlement(config, state, civ, index, tile_key(*tile), config.starting_outpost_pop, "hamlet",
                                     names[index])
        _build_on(state, outpost_id, "housing", layout.core_tile(state, state["settlements"][outpost_id], "housing", None))
        farm = layout.farm_tile(state, outpost_id)
        if farm is None:
            busy = layout.occupied_tiles(state) | layout.node_tiles(state)
            own = sorted((layout.biome_name(world_map, k) == "coast", k)
                         for k, v in state["territory"].items() if v == outpost_id and k not in busy)
            own = [k for _, k in own]  # inland first, coast only if nothing else
            if not own:
                raise _Reroll(f"outpost {outpost_id} has no free tile for a farm")
            fx, fy = _xy(own[0])
            _set_biome(state, fx, fy, "plains")
            farm = own[0]
        _build_on(state, outpost_id, "farm", farm)

    if len(chosen) < config.outposts_per_civ:
        raise _Reroll(f"{civ} found room for only {len(chosen)} outposts")
    _town_traits(config, state, seed, attempt, civ)
    civ_state["origin"] = state["settlements"][capital_id]["tile"]
    units.spawn(config, state, civ, "scout", capital_id, None, pay=False, ready_now=True)


def _town_traits(config: Config, state: dict, seed: int, attempt: int, civ: str) -> None:
    spec = config.civ(civ)
    draw = _draw(seed, attempt, "traits", civ)
    foreign_luxuries = sorted(s.luxury for s in config.civs if s.civ_id != civ)
    used_pairs: set[tuple[str, str]] = set()
    settlement_ids = sorted(k for k, v in state["settlements"].items() if v["civ"] == civ)
    for settlement_id in settlement_ids:
        settlement = state["settlements"][settlement_id]
        if settlement["capital"]:
            strong_options = [spec.rich_in[0]]
        else:
            strong_options = ["food"] + sorted({
                {"forest": "timber", "stone": "stone", "metal": "metal"}[n["kind"]]
                for n in state["nodes"].values()
                if n["kind"] != "luxury" and state["territory"].get(n["tile"]) == settlement_id
            })
        pairs = [(s, w) for s in strong_options for w in LINES if w != s and (s, w) not in used_pairs]
        if not pairs:  # every producible pair is taken; any unused pair keeps towns distinct
            pairs = [(s, w) for s in LINES for w in LINES if w != s and (s, w) not in used_pairs]
        strong, weak = pairs[draw.randrange(len(pairs))]
        used_pairs.add((strong, weak))
        settlement["specialty"] = {"strong": strong, "weak": weak}
        settlement["need"] = foreign_luxuries[draw.randrange(len(foreign_luxuries))]
        settlement["quirk"] = QUIRKS[draw.randrange(len(QUIRKS))]
