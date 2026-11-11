"""Units, sight, the known map and contact (rules 6 and 21)."""

import copy
import dataclasses
import json

import pytest

from fogline import actions, bots, engine, ledger, rules, sight, units, worldgen
from fogline.config import Config
from fogline.layout import is_land, square
from fogline.state import parse_tile_key, tile_key
from test_engine import _assert_conserved

CONFIG = dataclasses.replace(Config(), events_enabled=False)


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    return copy.deepcopy(start)


def _lonely_tile(state, distance=7):
    """Unclaimed land at least `distance` from every settlement and unit."""
    taken = [parse_tile_key(s["tile"]) for s in state["settlements"].values()]
    taken += [parse_tile_key(u["tile"]) for u in state["units"].values()]
    for y in range(8, 56):
        for x in range(8, 56):
            if (is_land(state["map"], x, y) and tile_key(x, y) not in state["territory"]
                    and all(max(abs(x - a), abs(y - b)) >= distance for a, b in taken)):
                return tile_key(x, y)
    raise AssertionError("no lonely tile")


def _next_to(state, settlement_id):
    centre = parse_tile_key(state["settlements"][settlement_id]["tile"])
    for x, y in square(centre, 2, state["map"]["size"])[1:]:
        if is_land(state["map"], x, y):
            return tile_key(x, y)
    raise AssertionError("no land next to " + settlement_id)


def _set_stock(state, civ_id, resource, amount):
    stocks = state["civs"][civ_id]["stocks"]
    rule = ledger.Rule.PRODUCTION if amount > stocks[resource] else ledger.Rule.RIOT
    ledger.apply(stocks, state["ledger"], None, civ_id, resource, amount - stocks[resource], rule, 0)


def test_every_civ_starts_with_a_ready_scout_drawn_from_its_capital(start):
    for civ_id in start["civs"]:
        ids = units.of_civ(start, civ_id)
        assert len(ids) == 1
        unit = start["units"][ids[0]]
        capital = start["settlements"][f"{civ_id}-0"]
        assert unit["kind"] == "scout" and unit["pop"] == 1 and unit["home"] == f"{civ_id}-0"
        assert units.is_ready(start, unit) and unit["tile"] == capital["tile"]
        assert capital["pop"] == CONFIG.starting_capital_pop - 1
        assert start["civs"][civ_id]["origin"] == capital["tile"]
    _assert_conserved(start)


def test_sight_is_a_square_of_radius_two_or_three_with_pathfinding(start):
    state = _fresh(start)
    tile = _lonely_tile(state)
    units.spawn(CONFIG, state, "verdance", "scout", "verdance-0", None, pay=False, ready_now=True, at=tile)
    x, y = parse_tile_key(tile)
    seen = sight.visible(CONFIG, state, "verdance")
    assert {tile_key(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)} <= seen
    assert tile_key(x + 3, y) not in seen and tile_key(x + 3, y + 3) not in seen
    state["civs"]["verdance"]["techs"].append("pathfinding")
    seen = sight.visible(CONFIG, state, "verdance")
    assert tile_key(x + 3, y + 3) in seen and tile_key(x + 4, y) not in seen


def test_the_known_map_grows_and_briefs_show_it_relative_to_the_capital(start):
    state = _fresh(start)
    tile = _lonely_tile(state)
    assert not sight.is_known(state, "verdance", *parse_tile_key(tile))
    units.spawn(CONFIG, state, "verdance", "scout", "verdance-0", None, pay=False, ready_now=True, at=tile)
    engine.tick(CONFIG, state)
    assert sight.is_known(state, "verdance", *parse_tile_key(tile))
    brief = engine.turns.brief(CONFIG, state, "verdance")
    ox, oy = parse_tile_key(state["civs"]["verdance"]["origin"])
    x, y = parse_tile_key(tile)
    assert "0,0" in brief["known"] and tile_key(x - ox, y - oy) in brief["known"]


def test_contact_is_logged_both_ways_and_wakes_both_civs(start):
    state = _fresh(start)
    units.spawn(CONFIG, state, "ironhold", "scout", "ironhold-0", None, pay=False, ready_now=True,
                at=_next_to(state, "verdance-1"))
    engine.tick(CONFIG, state)
    assert "verdance" in state["civs"]["ironhold"]["met"] and "ironhold" in state["civs"]["verdance"]["met"]
    contacts = {(e["civ"], e["detail"]) for e in state["events"] if e["kind"] == "contact"}
    assert {("ironhold", "verdance"), ("verdance", "ironhold")} <= contacts

    seen = {}

    def record(civ_id):
        def decide(brief):
            seen[civ_id] = brief
            return bots.idle(brief)
        return decide

    for civ_id in ("ironhold", "verdance"):  # asleep for a long while; only contact can wake them
        state["civs"][civ_id]["turn"].update(wake_at=999, last_woke=state["tick"])
    engine.tick(CONFIG, state, deciders={"ironhold": record("ironhold"), "verdance": record("verdance")})
    assert {"trigger": "contact", "detail": "Verdance"} in seen["ironhold"]["triggers"]
    assert {"trigger": "contact", "detail": "Ironhold"} in seen["verdance"]["triggers"]
    assert seen["verdance"]["met"] == ["Ironhold"]
    assert seen["ironhold"]["in_view"] == [] and seen["ironhold"]["foreign_sites"]


def test_no_brief_mentions_another_civ_before_contact(start):
    state = _fresh(start)
    briefs = []

    def watch(civ_id):
        def decide(brief):
            briefs.append((civ_id, brief))
            return bots.spiral_scout(brief)
        return decide

    engine.run(CONFIG, state, 60, deciders={c: watch(c) for c in state["civs"]})
    assert briefs
    for civ_id, brief in briefs:
        if brief["met"]:
            continue
        text = json.dumps(brief).lower()
        for other in state["civs"]:
            if other != civ_id:
                assert other not in text, (civ_id, other, brief["tick"])


def test_train_unit_reason_codes_cost_and_training_time(start):
    state = _fresh(start)
    train = actions.train_unit
    assert train(CONFIG, state, "verdance", "ironhold-0", "scout") == "not_own_settlement"
    assert train(CONFIG, state, "verdance", "verdance-0", "dragon") == "unknown_unit_kind"
    assert train(CONFIG, state, "verdance", "verdance-0", "soldiers") == "tech_missing"
    state["civs"]["verdance"]["techs"].append("drill")
    assert train(CONFIG, state, "verdance", "verdance-0", "soldiers") == "building_missing"
    assert train(CONFIG, state, "verdance", "verdance-1", "levy") == "not_enough_people"
    metal = state["civs"]["verdance"]["stocks"]["metal"]
    _set_stock(state, "verdance", "metal", 0)
    assert train(CONFIG, state, "verdance", "verdance-0", "levy") == "cannot_afford"
    _set_stock(state, "verdance", "metal", metal)

    capital = state["settlements"]["verdance-0"]
    pop = capital["pop"]
    assert train(CONFIG, state, "verdance", "verdance-0", "scout") is None
    new = state["units"]["verdance-u1"]
    assert capital["pop"] == pop - 1 and new["pop"] == 1 and not units.is_ready(state, new)
    assert state["ledger"]["verdance:food:train_cost"] == -15
    engine.tick(CONFIG, state)
    assert units.is_ready(state, new)
    engine.tick(CONFIG, state)
    assert any(e["kind"] == "idle" and e["detail"] == "verdance-u1" for e in state["events"])
    _assert_conserved(state)


def test_move_unit_reason_codes(start):
    state = _fresh(start)
    move = actions.move_unit
    known = sight.known_tiles(state, "verdance")
    assert move(CONFIG, state, "verdance", "nobody", known[0]) == "unknown_unit"
    # A real foreign id must answer like a made-up one, or the reply names a civ before contact.
    assert move(CONFIG, state, "verdance", "ironhold-u0", known[0]) == "unknown_unit"
    far = next(tile_key(x, y) for y in range(64) for x in range(64)
               if not sight.near_known(state, "verdance", tile_key(x, y), CONFIG.order_margin))
    assert move(CONFIG, state, "verdance", "verdance-u0", far) == "unknown_ground"
    actions.train_unit(CONFIG, state, "verdance", "verdance-0", "scout")
    assert move(CONFIG, state, "verdance", "verdance-u1", known[0]) == "in_training"

    for civ_id in sorted(state["civs"]):
        scout = units.of_civ(state, civ_id)[0]
        sea = [tile_key(x, y) for y in range(64) for x in range(64) if state["map"]["biome"][y][x] == "S"
               and sight.near_known(state, civ_id, tile_key(x, y), CONFIG.order_margin)]
        if sea:
            assert move(CONFIG, state, civ_id, scout, sea[0]) == "unreachable"
            return
    pytest.skip("no civ starts within reach of the sea on seed 1")


def test_a_scout_walks_its_route_at_four_points_a_tick_and_arrives(start):
    state = _fresh(start)
    scout = state["units"]["verdance-u0"]
    origin = scout["tile"]
    target, path = max(((t, units.route(CONFIG, state, origin, t)) for t in sight.known_tiles(state, "verdance")),
                       key=lambda pair: (len(pair[1] or []), pair[0]))
    assert len(path) >= 3
    assert actions.move_unit(CONFIG, state, "verdance", "verdance-u0", target) is None
    assert scout["path"] == units.route(CONFIG, state, origin, target)  # the same route every time
    for _ in range(len(path)):
        before = scout["tile"]
        engine.tick(CONFIG, state)
        walked = path[path.index(before) + 1:path.index(scout["tile"]) + 1] if before in path else \
            path[:path.index(scout["tile"]) + 1]
        cost = sum(engine.units.enter_cost(CONFIG, state["map"], *parse_tile_key(t)) for t in walked)
        assert cost <= CONFIG.units["scout"]["move"]
        if scout["tile"] == target:
            break
    assert scout["tile"] == target and scout["target"] == "" and scout["path"] == []
    assert any(e["kind"] == "arrived" and e["detail"] == "verdance-u0" for e in state["events"])


def test_disbanding_sends_people_home_and_only_on_own_land(start):
    state = _fresh(start)
    stray = units.spawn(CONFIG, state, "verdance", "scout", "verdance-0", None, pay=False, ready_now=True,
                        at=_lonely_tile(state))
    assert actions.disband_unit(CONFIG, state, "verdance", stray) == "not_in_territory"
    assert actions.disband_unit(CONFIG, state, "ironhold", "verdance-u0") == "unknown_unit"
    capital = state["settlements"]["verdance-0"]
    pop = capital["pop"]
    assert actions.disband_unit(CONFIG, state, "verdance", "verdance-u0") is None
    assert capital["pop"] == pop + 1 and "verdance-u0" not in state["units"]
    assert ledger.net_change(state["ledger"], "verdance-u0", "pop") == 0
    _assert_conserved(state)


def test_army_upkeep_grows_by_a_quarter_at_ten_army_units(start):
    state = _fresh(start)
    capital = state["settlements"]["verdance-0"]
    ledger.apply(capital, state["ledger"], None, "verdance-0", "pop", 60, ledger.Rule.BIRTH, 0)
    for _ in range(10):
        units.spawn(CONFIG, state, "verdance", "levy", "verdance-0", None, pay=False, ready_now=True)
    food = state["civs"]["verdance"]["stocks"]["food"]
    units.pay_upkeep(CONFIG, state, "verdance", None)
    # The scout eats 1; ten levies eat 10 x 1.25 = 12.5, rounded down once.
    assert food - state["civs"]["verdance"]["stocks"]["food"] == 1 + 12


def test_allocate_workers_checks_the_split(start):
    state = _fresh(start)
    allocate = actions.allocate_workers
    for bad in ({"food": 101}, {"magic": 10}, {"food": -1}, {"food": 60, "timber": 50}, {"food": True}, [50]):
        assert allocate(CONFIG, state, "verdance", bad) == "bad_allocation", bad
    assert allocate(CONFIG, state, "verdance", {"research": 30, "food": 70}) is None
    assert state["civs"]["verdance"]["allocation"] == {"food": 70, "research": 30}


def test_reorders_move_idle_people_first_then_the_busiest_line():
    workers = {"food": 5, "timber": 3, "stone": 0, "metal": 0, "luxury": 0, "research": 2}
    slots = {"food": 5, "timber": 5, "stone": 4, "metal": 0, "luxury": 0, "research": 4}
    rule = [{"stock": "stone", "below": 50, "workers": 3}]
    moved, budget = rules.reorder_shift(12, workers, slots, {"stone": 10}, rule, [3])
    assert moved["stone"] == 3 and moved["food"] == 4 and budget == [0]  # 2 idle, then 1 farmer
    unchanged, budget = rules.reorder_shift(12, workers, slots, {"stone": 50}, rule, [3])
    assert unchanged == workers and budget == [3]
    capped, budget = rules.reorder_shift(12, workers, {**slots, "stone": 1}, {"stone": 10}, rule, [3])
    assert capped["stone"] == 1 and budget == [2]
