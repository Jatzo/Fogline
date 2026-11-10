"""Movement costs and shortest paths on the tile map (docs/rules.md section 2)."""

import heapq

from fogline.config import Config

# One character per biome keeps the map compact in saved state.
BIOME_CODES = {"P": "plains", "C": "coast", "F": "forest", "D": "desert", "T": "tundra", "M": "mountains", "S": "sea"}
CODE_FOR = {name: code for code, name in BIOME_CODES.items()}
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def biome_at(world_map: dict, x: int, y: int) -> str:
    return BIOME_CODES[world_map["biome"][y][x]]


def is_river(world_map: dict, x: int, y: int) -> bool:
    return world_map["river"][y][x] == "1"


def in_bounds(world_map: dict, x: int, y: int) -> bool:
    size = world_map["size"]
    return 0 <= x < size and 0 <= y < size


def enter_cost(config: Config, world_map: dict, x: int, y: int, roads: frozenset[str] = frozenset()) -> int | None:
    """Movement points to enter a tile, or None if it can't be entered (sea)."""
    biome = biome_at(world_map, x, y)
    if biome == "sea":
        return None
    if f"{x},{y}" in roads:
        return 1
    cost = config.move_cost[biome]
    if is_river(world_map, x, y):
        cost += config.river_crossing_cost
    return cost


def path_costs(config: Config, world_map: dict, start: tuple[int, int],
               roads: frozenset[str] = frozenset()) -> dict[tuple[int, int], int]:
    """Dijkstra from start: the cheapest movement cost to every reachable tile."""
    best = {start: 0}
    queue = [(0, start)]
    while queue:
        cost, (x, y) = heapq.heappop(queue)
        if cost > best[(x, y)]:
            continue
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not in_bounds(world_map, nx, ny):
                continue
            step = enter_cost(config, world_map, nx, ny, roads)
            if step is None:
                continue
            new_cost = cost + step
            if new_cost < best.get((nx, ny), new_cost + 1):
                best[(nx, ny)] = new_cost
                heapq.heappush(queue, (new_cost, (nx, ny)))
    return best
