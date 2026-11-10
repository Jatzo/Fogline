"""Build queue, placement, contestable claims and growth stages (rules 15)."""

import copy
import dataclasses

import pytest

from fogline import actions, construction, engine, ledger, rules, techs, worldgen
from fogline.config import Config
from fogline.layout import STAGE_RADIUS, square
from fogline.state import parse_tile_key, tile_key

CONFIG = dataclasses.replace(Config(), events_enabled=False)


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    return copy.deepcopy(start)


def _types(settlement):
    return [b["type"] for b in settlement["buildings"]]


def _set_stock(state, civ_id, resource, amount):
    stocks = state["civs"][civ_id]["stocks"]
    rule = ledger.Rule.PRODUCTION if amount > stocks[resource] else ledger.Rule.RIOT
    ledger.apply(stocks, state["ledger"], None, civ_id, resource, amount - stocks[resource], rule, 0)


def _free_footprint_tile(state, settlement_id):
    settlement = state["settlements"][settlement_id]
    centre = parse_tile_key(settlement["tile"])
    for x, y in reversed(square(centre, STAGE_RADIUS[settlement["stage"]], state["map"]["size"])):
        tile = tile_key(x, y)
        if construction._hint_owner(CONFIG, state, settlement_id, "housing", tile) == settlement_id:
            return tile
    raise AssertionError("no free footprint tile")


def test_build_reason_codes(start):
    state = _fresh(start)
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "castle") == "unknown_building"
    assert actions.build(CONFIG, state, "verdance", "ironhold-0", "housing") == "not_own_settlement"
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "library") == "tech_missing"
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "housing", "nowhere") == "bad_tile"
    farm = next(b for b in state["settlements"]["verdance-0"]["buildings"] if b["type"] == "farm")
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "housing", farm["tile"]) == "tile_taken"
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "farm", farm["tile"]) == "tile_taken"
    for _ in range(CONFIG.build_queue_max):
        assert actions.build(CONFIG, state, "verdance", "verdance-0", "housing") is None
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "housing") == "queue_full"


def test_housing_is_paid_once_and_stands_after_one_tick(start):
    state = _fresh(start)
    before = _types(state["settlements"]["verdance-1"]).count("housing")
    assert actions.build(CONFIG, state, "verdance", "verdance-1", "housing") is None
    engine.tick(CONFIG, state)
    settlement = state["settlements"]["verdance-1"]
    assert _types(settlement).count("housing") == before + 1
    new = settlement["buildings"][-1]
    assert new["built_tick"] == 0
    assert construction._in_footprint(settlement, new["tile"])
    assert state["ledger"]["verdance:timber:build_cost"] == -10
    assert state["civs"]["verdance"]["build_queue"] == []


def test_a_valid_tile_hint_is_used_and_a_bad_one_is_overridden(start):
    state = _fresh(start)
    hint = _free_footprint_tile(state, "saltreach-0")
    actions.build(CONFIG, state, "saltreach", "saltreach-0", "housing", hint)
    engine.tick(CONFIG, state)
    assert state["settlements"]["saltreach-0"]["buildings"][-1]["tile"] == hint

    state = _fresh(start)
    outside = next(tile_key(x, y) for y in range(64) for x in range(64) if tile_key(x, y) not in state["territory"])
    actions.build(CONFIG, state, "saltreach", "saltreach-0", "housing", outside)
    engine.tick(CONFIG, state)
    placed = state["settlements"]["saltreach-0"]["buildings"][-1]["tile"]
    assert placed != outside and state["territory"][placed] == "saltreach-0"


def test_an_unaffordable_build_waits_without_paying(start):
    state = _fresh(start)
    _set_stock(state, "frostmark", "timber", 0)
    actions.build(CONFIG, state, "frostmark", "frostmark-0", "mine")
    engine.tick(CONFIG, state)
    entry = state["civs"]["frostmark"]["build_queue"][0]
    assert not entry["started"] and "frostmark:timber:build_cost" not in state["ledger"]
    _set_stock(state, "frostmark", "timber", 100)
    engine.tick(CONFIG, state)
    assert state["civs"]["frostmark"]["build_queue"][0]["started"]


def test_one_build_at_a_time_per_settlement_and_mines_take_two_ticks(start):
    state = _fresh(start)
    capital = state["settlements"]["ironhold-0"]
    mines = _types(capital).count("mine")
    houses = _types(capital).count("housing")
    actions.build(CONFIG, state, "ironhold", "ironhold-0", "mine")
    actions.build(CONFIG, state, "ironhold", "ironhold-0", "housing")
    engine.tick(CONFIG, state)
    assert _types(capital).count("mine") == mines and _types(capital).count("housing") == houses
    engine.tick(CONFIG, state)
    assert _types(capital).count("mine") == mines + 1 and _types(capital).count("housing") == houses
    engine.tick(CONFIG, state)
    assert _types(capital).count("housing") == houses + 1


def test_rebuilding_a_ruin_costs_half_and_repair_a_quarter(start):
    state = _fresh(start)
    capital = state["settlements"]["verdance-0"]
    farm = next(b for b in capital["buildings"] if b["type"] == "farm")
    camp = next(b for b in capital["buildings"] if b["type"] == "lumber_camp")
    farm["ruin"] = True
    camp["damaged"] = True
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "farm", farm["tile"]) is None
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "farm", farm["tile"]) == "already_queued"
    engine.tick(CONFIG, state)
    assert not farm["ruin"] and farm["built_tick"] == 0
    assert state["ledger"]["verdance:timber:build_cost"] == -5
    assert actions.build(CONFIG, state, "verdance", "verdance-0", "lumber_camp", camp["tile"]) is None
    engine.tick(CONFIG, state)
    assert not camp["damaged"]
    assert state["ledger"]["verdance:timber:build_cost"] == -6  # 5 + a quarter of 5, rounded down


def test_a_node_within_reach_of_own_land_is_claimed_by_the_nearest_settlement(start):
    state = _fresh(start)
    node_id, node = next((k, n) for k, n in sorted(state["nodes"].items())
                         if k.startswith("contest-") and n["tile"] not in state["territory"])
    building = "lumber_camp" if node["kind"] == "forest" else "mine"
    nx, ny = parse_tile_key(node["tile"])
    # Pretend the frontier has reached 3 tiles from the node.
    frontier = tile_key(nx + 3 if nx + 3 < 64 else nx - 3, ny)
    state["territory"].pop(frontier, None)
    state["territory"][frontier] = "dunerunners-0"
    assert actions.build(CONFIG, state, "dunerunners", "dunerunners-0", building, node["tile"]) is None
    entry = state["civs"]["dunerunners"]["build_queue"][0]
    owner = entry["settlement"]
    engine.run(CONFIG, state, CONFIG.buildings[building]["ticks"])
    assert state["territory"][node["tile"]] == owner
    assert state["settlements"][owner]["buildings"][-1]["tile"] == node["tile"]


def test_a_worked_out_node_takes_no_new_mine(start):
    state = _fresh(start)
    node_id, node = next((k, n) for k, n in sorted(state["nodes"].items())
                         if n["kind"] in ("stone", "metal") and state["territory"].get(n["tile"]) == "ironhold-0"
                         and n["tile"] not in {b["tile"] for b in state["settlements"]["ironhold-0"]["buildings"]})
    assert construction.terrain_ok(CONFIG, state, "ironhold", "mine", node["tile"])
    ledger.apply(node, state["ledger"], None, node_id, "node", -node["node"], ledger.Rule.EXTRACTION, 0)
    assert not construction.terrain_ok(CONFIG, state, "ironhold", "mine", node["tile"])


@pytest.mark.parametrize("pop, buildings, stage", [
    (24, ["housing"] * 20, "hamlet"),
    (25, ["housing"] * 3, "hamlet"),
    (25, ["housing"] * 4, "village"),
    (60, ["housing"] * 8, "village"),
    (60, ["housing"] * 7 + ["library"], "town"),
    (150, ["housing"] * 13 + ["market"], "town"),
    (150, ["housing"] * 12 + ["market", "town_walls"], "city"),
])
def test_stage_thresholds(pop, buildings, stage):
    assert rules.stage_for(CONFIG, pop, buildings) == stage


def test_a_settlement_grows_a_stage_and_claims_more_land(start):
    state = _fresh(start)
    capital = state["settlements"]["verdance-0"]
    owned = sum(1 for sid in state["territory"].values() if sid == "verdance-0")
    capital["buildings"].append({"type": "library", "tile": _free_footprint_tile(state, "verdance-0"),
                                 "built_tick": 0, "owed": False, "arrears_ticks": 0, "damaged": False, "ruin": False})
    ledger.apply(capital, state["ledger"], None, "verdance-0", "pop", 25, ledger.Rule.BIRTH, 0)
    engine.tick(CONFIG, state)
    assert capital["stage"] == "town"
    assert sum(1 for sid in state["territory"].values() if sid == "verdance-0") > owned


def test_a_stage_drops_after_four_ticks_below_its_band_and_keeps_its_land(start):
    state = _fresh(start)
    capital = state["settlements"]["frostmark-0"]
    ledger.apply(capital, state["ledger"], None, "frostmark-0", "pop", 20 - capital["pop"],
                 ledger.Rule.DEATH_PLAGUE, 0)
    owned = sum(1 for sid in state["territory"].values() if sid == "frostmark-0")
    engine.run(CONFIG, state, 3)
    assert capital["stage"] == "village"
    engine.tick(CONFIG, state)
    assert capital["stage"] == "hamlet"
    assert sum(1 for sid in state["territory"].values() if sid == "frostmark-0") == owned


def test_coast_gives_fishing_slots_and_a_harbour_widens_them(start):
    state = _fresh(start)
    coastal = {sid for tile, sid in state["territory"].items() if engine.biome_name(state["map"], tile) == "coast"}
    settlement_id = sorted(coastal)[0]
    node_at = {n["tile"]: k for k, n in state["nodes"].items()}

    def fishing_slots():
        sites = engine._work_sites(CONFIG, state, settlement_id, node_at, coastal)
        return [s["slots"] for s in sites if s["work"] == "fishing"]

    assert fishing_slots() == [CONFIG.slots["fishing_no_harbour"]]
    state["settlements"][settlement_id]["buildings"].append(
        {"type": "harbour", "tile": "0,0", "built_tick": 0, "owed": False, "arrears_ticks": 0, "damaged": False,
         "ruin": False})
    assert fishing_slots() == [CONFIG.slots["fishing_harbour"]]


def test_irrigation_lets_farms_use_desert_by_a_river():
    for seed in range(1, 6):
        state = worldgen.generate(CONFIG, seed)
        world = state["map"]
        for y in range(world["size"]):
            for x in range(world["size"]):
                if construction._irrigable(state, x, y) and not engine.is_river(world, x, y):
                    civ_id = "dunerunners"
                    assert not construction.terrain_ok(CONFIG, state, civ_id, "farm", tile_key(x, y))
                    state["civs"][civ_id]["techs"].append("irrigation")
                    assert construction.terrain_ok(CONFIG, state, civ_id, "farm", tile_key(x, y))
                    return
    pytest.skip("no desert tile beside a river on seeds 1 to 5")


def _busy_civ(state):
    """A crude builder: always researching, and always building something when the queue is short."""
    now = state["tick"]
    for civ_id in sorted(state["civs"]):
        civ = state["civs"][civ_id]
        if not civ["research"]["tech"]:
            options = techs.available(state, civ_id)
            if options:
                actions.set_research(CONFIG, state, civ_id, options[0])
        if len(civ["build_queue"]) < 2:
            own = engine.settlements_of(state, civ_id)
            building = ("housing", "farm", "mine", "lumber_camp")[now % 4]
            actions.build(CONFIG, state, civ_id, own[now % len(own)], building)


@pytest.mark.parametrize("seed", [1, 2])
def test_conservation_holds_with_building_and_research_over_200_ticks(seed):
    config = Config()
    state = worldgen.generate(config, seed)
    for _ in range(200):
        _busy_civ(state)
        engine.tick(config, state)
    totals = state["ledger"]
    for civ_id, civ in state["civs"].items():
        for stock, value in civ["stocks"].items():
            assert ledger.net_change(totals, civ_id, stock) == value, (civ_id, stock)
    for settlement_id, settlement in state["settlements"].items():
        assert ledger.net_change(totals, settlement_id, "pop") == settlement["pop"]
    for node_id, node in state["nodes"].items():
        assert ledger.net_change(totals, node_id, "node") == node["node"]
    assert any(len(c["techs"]) > len(worldgen.STARTING_TECHS) for c in state["civs"].values())
    assert any(e["kind"] == "built" for e in state["events"])
