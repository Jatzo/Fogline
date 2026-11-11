"""Economy tick tests: conservation over long runs, plus engine behaviour the formulas alone can't show."""

import copy
import dataclasses

import pytest

from fogline import engine, ledger, worldgen
from fogline.config import Config
from fogline.state import state_hash

CONFIG = Config()
QUIET = dataclasses.replace(CONFIG, events_enabled=False)


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    return copy.deepcopy(start)


def _assert_conserved(state):
    totals = state["ledger"]
    for civ_id, civ in state["civs"].items():
        for stock, value in civ["stocks"].items():
            assert ledger.net_change(totals, civ_id, stock) == value, (civ_id, stock)
    for settlement_id, settlement in state["settlements"].items():
        assert ledger.net_change(totals, settlement_id, "pop") == settlement["pop"], settlement_id
    for node_id, node in state["nodes"].items():
        assert ledger.net_change(totals, node_id, "node") == node["node"], node_id
    for unit_id, unit in state["units"].items():
        assert ledger.net_change(totals, unit_id, "pop") == unit["pop"], unit_id
    # An owner that no longer exists (a disbanded unit) must hold nothing.
    live = set(state["civs"]) | set(state["settlements"]) | set(state["nodes"]) | set(state["units"])
    gone = {key.split(":")[0] for key in totals} - live
    for owner in gone:
        assert ledger.net_change(totals, owner, "pop") == 0, owner


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_stock_is_explained_by_the_ledger_over_200_ticks(seed):
    state = worldgen.generate(CONFIG, seed)
    before = dict(state["ledger"])
    log = []
    engine.run(CONFIG, state, 200, log)
    _assert_conserved(state)
    # The per-tick log explains exactly what the running totals gained during the run.
    summed = {}
    for entry in log:
        key = f"{entry['owner']}:{entry['stock']}:{entry['rule']}"
        summed[key] = summed.get(key, 0) + entry["delta"]
    gained = {key: value - before.get(key, 0) for key, value in state["ledger"].items()
              if value != before.get(key, 0)}
    assert {k: v for k, v in summed.items() if v} == gained


def test_conservation_holds_through_riots_and_secession(start):
    state = _fresh(start)
    for _ in range(40):  # hold every civ in turmoil
        for civ in state["civs"].values():
            civ["stability"] = 0
        engine.tick(CONFIG, state)
    kinds = {event["kind"] for event in state["events"]}
    assert {"riot", "secession"} <= kinds
    _assert_conserved(state)


def test_every_world_event_keeps_the_ledger_whole(start):
    state = _fresh(start)
    stormy = dataclasses.replace(CONFIG, world_event_chance=1000)
    engine.run(stormy, state, 60)
    kinds = {event["kind"] for event in state["events"]}
    assert set(engine.WORLD_EVENTS) <= kinds, kinds
    assert any(node_id.startswith("found-") for node_id in state["nodes"])
    _assert_conserved(state)


@pytest.mark.parametrize("now, winter", [(0, 3), (2, 3), (3, 7), (5, 7)])
def test_harsh_winter_lands_on_the_next_winter(now, winter):
    assert engine.next_winter(now) == winter


def test_the_same_start_gives_the_same_hash(start):
    first, second = _fresh(start), _fresh(start)
    engine.run(CONFIG, first, 50)
    engine.run(CONFIG, second, 50)
    assert state_hash(first) == state_hash(second)


def test_first_tick_production_for_a_normal_capital(start):
    state = _fresh(start)
    capital = state["settlements"]["verdance-0"]
    engine.tick(QUIET, state)
    # 40 people, default allocation: 20 farmers, 5 foresters, 4 at the mine, 2 on luxury, 4 scholars.
    workers = capital["workers"]
    assert workers["food"] == 20 and workers["timber"] == 5 and workers["research"] == 4
    assert workers["luxury"] == 2
    assert sum(workers.values()) <= capital["pop"]


def test_food_short_civ_keeps_to_its_worker_cap(start):
    state = _fresh(start)
    engine.tick(QUIET, state)
    for civ_id, civ in state["civs"].items():
        food = sum(state["settlements"][sid]["workers"]["food"] for sid in engine.settlements_of(state, civ_id))
        if civ["food_worker_cap"]:
            assert food <= civ["food_worker_cap"], civ_id
        else:
            assert food > QUIET.short_food_worker_cap, civ_id


def test_no_growth_before_a_full_four_tick_food_window(start):
    state = _fresh(start)
    births = lambda s: sum(v for k, v in s["ledger"].items() if k.endswith(":pop:birth"))  # noqa: E731
    engine.run(QUIET, state, 3)
    assert births(state) == 0
    engine.run(QUIET, state, 12)
    assert births(state) > 0


def test_starving_civ_loses_a_quarter_of_its_unfed_rounded_up(start):
    state = _fresh(start)
    civ = state["civs"]["ironhold"]
    ledger.apply(civ["stocks"], state["ledger"], None, "ironhold", "food", -civ["stocks"]["food"],
                 ledger.Rule.RIOT, 0)
    pop = engine.civ_pop(state, "ironhold")
    engine.tick(QUIET, state)
    produced = state["ledger"]["ironhold:food:production"]
    unfed = pop - produced
    deaths = -sum(v for k, v in state["ledger"].items()
                  if k.startswith("ironhold-") and k.endswith(":pop:death_starvation"))
    assert deaths == -(-unfed // 4)
    # With nothing to eat the starting scout can't be fed either, so its person comes home.
    assert "ironhold-u0" not in state["units"]
    assert civ["stability"] < QUIET.stability_start


def test_unpaid_upkeep_ruins_buildings_after_eight_ticks_but_never_fields_or_camps(start):
    state = _fresh(start)
    civ = state["civs"]["frostmark"]
    ledger.apply(civ["stocks"], state["ledger"], None, "frostmark", "stone", -civ["stocks"]["stone"],
                 ledger.Rule.RIOT, 0)
    capital = state["settlements"]["frostmark-0"]
    # Keep the mine off stone so nothing pays the bill.
    civ["allocation"] = {"food": 100}
    engine.run(QUIET, state, 4)
    assert all(b["arrears_ticks"] == 1 for b in capital["buildings"])
    engine.run(QUIET, state, 7)
    assert all(b["arrears_ticks"] == 8 or b["ruin"] for b in capital["buildings"])
    engine.tick(QUIET, state)
    for building in capital["buildings"]:
        if building["type"] in engine.EXTRACTION:  # farms, camps and mines stay, at half output
            assert not building["ruin"] and building["arrears_ticks"] > QUIET.ruin_after_ticks
        else:
            assert building["ruin"]
    _assert_conserved(state)


def test_events_are_off_when_disabled(start):
    state = _fresh(start)
    engine.run(QUIET, state, 100)
    assert not [e for e in state["events"] if e["kind"] in (*engine.WORLD_EVENTS, "quirk")]
