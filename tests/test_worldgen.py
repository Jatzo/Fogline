"""Worldgen tests: the map meets docs/rules.md section 2 on many seeds, and is reproducible."""

import pytest

from fogline import ledger, worldgen
from fogline.config import Config
from fogline.state import state_hash

CONFIG = Config()
SEEDS = range(1, 21)


@pytest.fixture(scope="module")
def worlds():
    return {seed: worldgen.generate(CONFIG, seed) for seed in SEEDS}


def _xy(tile):
    x, y = tile.split(",")
    return int(x), int(y)


def test_the_same_seed_gives_the_same_world():
    assert state_hash(worldgen.generate(CONFIG, 7)) == state_hash(worldgen.generate(CONFIG, 7))


def test_different_seeds_give_different_worlds(worlds):
    assert len({state_hash(w) for w in worlds.values()}) == len(worlds)


def test_capitals_are_all_reachable_by_land_and_far_enough_apart(worlds):
    for seed, world in worlds.items():
        for pair, cost in worldgen.capital_path_costs(CONFIG, world).items():
            assert cost is not None, (seed, pair)
            assert cost >= CONFIG.min_capital_path_cost, (seed, pair, cost)


def test_every_civ_has_a_capital_and_three_outposts_on_their_own_land(worlds):
    for world in worlds.values():
        for civ in world["civs"]:
            settlements = {k: v for k, v in world["settlements"].items() if v["civ"] == civ}
            assert len(settlements) == 1 + CONFIG.outposts_per_civ
            for settlement_id, settlement in settlements.items():
                assert world["territory"][settlement["tile"]] == settlement_id


def test_outposts_mostly_face_away_from_the_nearest_neighbour(worlds):
    facing, total = 0, 0
    for world in worlds.values():
        capitals = {civ: _xy(world["settlements"][f"{civ}-0"]["tile"]) for civ in world["civs"]}
        for civ, (cx, cy) in capitals.items():
            nearest = min((c for c in capitals if c != civ),
                          key=lambda c: ((capitals[c][0] - cx) ** 2 + (capitals[c][1] - cy) ** 2, c))
            ax, ay = cx - capitals[nearest][0], cy - capitals[nearest][1]
            for index in range(1, 1 + CONFIG.outposts_per_civ):
                ox, oy = _xy(world["settlements"][f"{civ}-{index}"]["tile"])
                facing += (ox - cx) * ax + (oy - cy) * ay > 0
                total += 1
    # Coasts with sea on the far side fall back to any side, so allow a few.
    assert facing * 100 // total >= 80, (facing, total)


def test_starting_buildings_match_the_rules(worlds):
    for world in worlds.values():
        for civ in world["civs"]:
            capital = world["settlements"][f"{civ}-0"]
            kinds = sorted(b["type"] for b in capital["buildings"])
            assert kinds.count("housing") == 5 and kinds.count("farm") == 4
            assert kinds.count("lumber_camp") == 1 and kinds.count("mine") == 1 and kinds.count("workshop") == 1
            for index in range(1, 1 + CONFIG.outposts_per_civ):
                outpost = world["settlements"][f"{civ}-{index}"]
                assert sorted(b["type"] for b in outpost["buildings"]) == ["farm", "housing"]


def test_no_two_buildings_or_nodes_share_a_tile_and_all_are_on_the_map(worlds):
    for world in worlds.values():
        size = world["map"]["size"]
        building_tiles = [b["tile"] for s in world["settlements"].values() for b in s["buildings"]]
        building_tiles += [s["tile"] for s in world["settlements"].values()]
        assert len(building_tiles) == len(set(building_tiles))
        node_tiles = [n["tile"] for n in world["nodes"].values()]
        assert len(node_tiles) == len(set(node_tiles))
        for tile in building_tiles + node_tiles:
            x, y = _xy(tile)
            assert 0 <= x < size and 0 <= y < size
            assert world["map"]["biome"][y][x] != "S"


def test_shortages_get_only_small_home_nodes_and_the_mine_sits_on_a_full_node(worlds):
    small_kind = {"timber": "forest", "stone": "stone", "metal": "metal"}
    for world in worlds.values():
        for spec in CONFIG.civs:
            home = [n for n in world["nodes"].values() if n["home"] == spec.civ_id and n["kind"] != "luxury"]
            for resource in ("timber", "stone", "metal"):
                of_kind = [n for n in home if n["kind"] == small_kind[resource]]
                if resource in spec.short_of:
                    assert len(of_kind) == 1 and of_kind[0]["small"]
                else:
                    assert of_kind and not any(n["small"] for n in of_kind)
            assert world["civs"][spec.civ_id]["food_worker_cap"] == (
                CONFIG.short_food_worker_cap if "food" in spec.short_of else 0)
            mine = next(b for b in world["settlements"][f"{spec.civ_id}-0"]["buildings"] if b["type"] == "mine")
            mined = next(n for n in world["nodes"].values() if n["tile"] == mine["tile"])
            assert not mined["small"]


def test_contestable_nodes_exist_and_belong_to_nobody(worlds):
    for world in worlds.values():
        contest = [n for n in world["nodes"].values() if n["home"] == ""]
        assert CONFIG.contestable_nodes_min <= len(contest) <= CONFIG.contestable_nodes_max
        assert not any(n["small"] for n in contest)


def test_every_town_has_a_distinct_specialty_a_foreign_need_and_a_quirk(worlds):
    for world in worlds.values():
        for spec in CONFIG.civs:
            towns = [s for s in world["settlements"].values() if s["civ"] == spec.civ_id]
            pairs = [(t["specialty"]["strong"], t["specialty"]["weak"]) for t in towns]
            assert len(set(pairs)) == len(pairs)
            assert all(strong != weak for strong, weak in pairs)
            capital = world["settlements"][f"{spec.civ_id}-0"]
            assert capital["specialty"]["strong"] == spec.rich_in[0]
            for town in towns:
                assert town["need"] and town["need"] != spec.luxury
                assert town["quirk"] in worldgen.QUIRKS


def test_worldgen_creates_every_stock_through_the_ledger(worlds):
    for world in worlds.values():
        for civ, civ_state in world["civs"].items():
            for resource, amount in civ_state["stocks"].items():
                assert ledger.net_change(world["ledger"], civ, resource) == amount
        for settlement_id, settlement in world["settlements"].items():
            assert ledger.net_change(world["ledger"], settlement_id, "pop") == settlement["pop"]
        for node_id, node in world["nodes"].items():
            assert ledger.net_change(world["ledger"], node_id, "node") == node["node"]


def test_rivers_reach_the_forest_and_desert_capitals(worlds):
    for world in worlds.values():
        for spec in CONFIG.civs:
            if spec.home_biome not in ("forest", "desert"):
                continue
            cx, cy = _xy(world["settlements"][f"{spec.civ_id}-0"]["tile"])
            near = [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
            assert any(world["map"]["river"][y][x] == "1" for x, y in near)
