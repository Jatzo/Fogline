"""Trade, caravans and escrow (Phase 3 M17; rules 8, 11 and 15.5). The 3a "done when" lives here:
a scripted trader forces a trade through the engine path, and a blueprint sale unlocks a tech."""

import copy
import dataclasses
import json

import pytest

from fogline import actions, bots, engine, observation, paths, schema, snapshot, trade, units, worldgen
from fogline.config import Config
from fogline.state import state_hash
from test_engine import _assert_conserved

CONFIG = Config()


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _pair(start, caravans=1):
    """Verdance and Saltreach have met, each with ready caravans at its capital."""
    state = copy.deepcopy(start)
    for a, b in (("verdance", "saltreach"), ("saltreach", "verdance")):
        state["civs"][a]["met"][b] = 0
    for civ_id in ("verdance", "saltreach"):
        for _ in range(caravans):
            units.spawn(CONFIG, state, civ_id, "caravan", f"{civ_id}-0", None, pay=False, ready_now=True)
    return state


def _offer(state, give, get, expires_in=8, giver="verdance", to="Saltreach"):
    return actions.dispatch(CONFIG, state, giver, {"kind": "offer_trade", "to": to, "give": give, "get": get,
                                                   "expires_in": expires_in})


def _run_until_done(state, offer_id, ticks=120, config=CONFIG):
    for _ in range(ticks):
        engine.tick(config, state)
        _assert_conserved(state)
        if state["offers"][offer_id]["status"] == trade.DONE:
            return
    raise AssertionError(f"offer {offer_id} never finished: {state['offers'][offer_id]['status']}")


def test_scripted_traders_complete_a_trade_through_the_engine(start):
    state = _pair(start)
    deciders = {c: bots.make_trader(CONFIG, c) for c in ("verdance", "saltreach")}
    for _ in range(150):
        engine.tick(CONFIG, state, deciders=deciders)
        _assert_conserved(state)
        if any(o["status"] == trade.DONE for o in state["offers"].values()):
            break
    done = [o for o in state["offers"].values() if o["status"] == trade.DONE]
    assert done, [o["status"] for o in state["offers"].values()]
    delivered = [e for e in state["events"] if e["kind"] == "delivered"]
    assert {e["civ"] for e in delivered} == {"verdance", "saltreach"}


def test_goods_go_into_escrow_and_arrive_less_the_fee(start):
    state = _pair(start)
    before_v, before_s = dict(state["civs"]["verdance"]["stocks"]), dict(state["civs"]["saltreach"]["stocks"])
    assert _offer(state, {"food": 100}, {"stone": 55}) is None
    offer = state["offers"]["o0"]
    assert state["civs"]["verdance"]["stocks"]["food"] == before_v["food"] - 100
    assert offer["escrow"]["give"] == {"food": 100}
    assert actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": True}) is None
    _run_until_done(state, "o0")
    # No market on either side: 10% of each good, rounded down, is destroyed (rules 8).
    assert state["civs"]["saltreach"]["stocks"]["food"] >= before_s["food"] + 90 - 200  # it ate meanwhile
    fees = {k: v for k, v in state["ledger"].items() if k.endswith(":market_fee")}
    assert sorted(-v for v in fees.values()) == [5, 10]  # 55 stone -> 5, 100 food -> 10


def test_a_fair_trade_raises_each_sides_view_of_the_other(start):
    state = _pair(start)
    views = (state["reputation"]["saltreach"]["verdance"], state["reputation"]["verdance"]["saltreach"])
    _offer(state, {"food": 100}, {"stone": 50})
    actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": True})
    _run_until_done(state, "o0", config=dataclasses.replace(CONFIG, reputation_drift_every=10 ** 6))  # no drift
    after = (state["reputation"]["saltreach"]["verdance"], state["reputation"]["verdance"]["saltreach"])
    assert [a - b for a, b in zip(after, views)] == [5, 5]  # +3 delivered, +2 within 25% of value
    assert state["prices"]["stone"] == 2000  # 100 food for 50 stone: 2 food each


def test_an_offer_nobody_answers_expires_and_returns_everything(start):
    state = _pair(start)
    food = state["civs"]["verdance"]["stocks"]["food"]
    _offer(state, {"food": 100}, {"stone": 10}, expires_in=2)
    caravan = state["offers"]["o0"]["caravans"]["give"][0]
    assert state["units"][caravan]["reserved"] == "o0"
    assert actions.dispatch(CONFIG, state, "verdance", {"kind": "move_unit", "unit": caravan, "to": "1,0"}) == "unit_busy"
    for _ in range(3):
        engine.tick(CONFIG, state)
    assert state["offers"]["o0"]["status"] == trade.EXPIRED
    assert state["units"][caravan]["reserved"] == "" and state["offers"]["o0"]["escrow"]["give"] == {"food": 0}
    assert any(e["kind"] == "offer_expiring" and e["civ"] == "saltreach" for e in state["events"])
    assert state["civs"]["verdance"]["stocks"]["food"] > food - 100  # back, less what was eaten
    _assert_conserved(state)


def test_a_refused_offer_returns_the_goods_at_once(start):
    state = _pair(start)
    food = state["civs"]["verdance"]["stocks"]["food"]
    _offer(state, {"food": 100}, {"stone": 10})
    actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": False})
    assert state["civs"]["verdance"]["stocks"]["food"] == food and state["offers"]["o0"]["status"] == trade.REJECTED
    _assert_conserved(state)


def test_trade_needs_caravans_goods_and_a_known_partner(start):
    state = _pair(start, caravans=0)
    assert _offer(state, {"food": 100}, {"stone": 10}) == "no_caravan"
    state = _pair(start)
    assert _offer(state, {"food": 10 ** 6}, {}) == "not_enough_goods"
    assert _offer(state, {"gold": 5}, {}) == "bad_goods"
    assert _offer(state, {"food": 10}, {}, to="Ironhold") == "unknown_civ"
    assert _offer(state, {"food": 150}, {}) == "no_caravan"  # 150 needs two caravans of 100
    assert actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o99", "accept": True}) \
        == "unknown_offer"


def test_a_blueprint_unlocks_a_tech_only_for_a_buyer_who_can_use_it(start):
    state = _pair(start)
    state["civs"]["verdance"]["techs"] += ["writing", "storage", "markets", "printing"]
    held = list(state["civs"]["saltreach"]["techs"])
    assert "writing" not in held
    _offer(state, {"blueprint:writing": 1, "blueprint:printing": 1}, {})  # aid: two blueprints
    actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": True})
    _run_until_done(state, "o0")
    techs_after = state["civs"]["saltreach"]["techs"]
    assert "writing" in techs_after  # basic_crafts is a starting tech
    assert "printing" not in techs_after  # needs markets, which saltreach lacks
    kinds = [e["kind"] for e in state["events"] if e["civ"] == "saltreach"]
    assert "blueprint_destroyed" in kinds and "printing" in state["civs"]["verdance"]["techs"]


def test_a_blueprint_in_an_offer_that_expires_is_logged_as_destroyed(start):
    state = _pair(start)
    state["civs"]["verdance"]["techs"].append("writing")
    _offer(state, {"blueprint:writing": 1}, {}, expires_in=1)
    for _ in range(2):
        engine.tick(CONFIG, state)
    assert state["offers"]["o0"]["status"] == trade.EXPIRED
    kinds = [e["kind"] for e in state["events"] if e["civ"] == "verdance" and "o0" in e["detail"]]
    assert kinds.count("blueprint_minted") == 1 and kinds.count("blueprint_destroyed") == 1


def test_caravans_and_trade_orders_dont_exist_before_contact(start):
    state = copy.deepcopy(start)
    order = {"kind": "train_unit", "settlement": "verdance-0", "unit_kind": "caravan"}
    assert actions.dispatch(CONFIG, state, "verdance", order) == "unknown_unit_kind"
    for kind in ("caravan", "zebra"):  # the same answer, so a probe can't tell a hidden unit from a made-up one
        probe = {"kind": "train_unit", "settlement": "nowhere", "unit_kind": kind}
        assert actions.dispatch(CONFIG, state, "verdance", probe) == "unknown_unit_kind"
    text = json.dumps(schema.json_schema(CONFIG))
    assert "caravan" not in text and "offer_trade" not in text and "respond_trade" not in text
    assert "caravan" in json.dumps(schema.json_schema(CONFIG, ["Saltreach"]))


def test_an_open_offer_shows_on_both_sides_and_wakes_the_receiver(start):
    state = _pair(start)
    _offer(state, {"food": 50}, {"stone": 20})
    for civ_id, name in (("verdance", "Verdance"), ("saltreach", "Verdance")):
        offers = observation.observe(CONFIG, state, civ_id)["offers"]
        assert [o["from"] for o in offers] == [name]
    assert any(e["kind"] == "offer" and e["civ"] == "saltreach" for e in state["events"])
    dossier = observation.observe(CONFIG, state, "saltreach")["dossiers"][0]
    assert dossier["name"] == "Verdance" and dossier["offers_received"] == 1


def test_six_caravan_crossings_wear_a_track(start):
    state = copy.deepcopy(start)
    world_map = state["map"]
    x, y = next((x, y) for y in range(10, 60) for x in range(10, 60) if world_map["biome"][y][x] == "F")
    before = paths.enter_cost(CONFIG, world_map, x, y)
    for _ in range(CONFIG.track_passes):
        units._wear(CONFIG, world_map, f"{x},{y}")
    assert f"{x},{y}" in world_map["tracks"]
    assert paths.enter_cost(CONFIG, world_map, x, y) == max(1, before - 1)


def test_a_run_saved_with_a_caravan_on_the_road_resumes_to_the_same_world(start, tmp_path):
    state = _pair(start)
    _offer(state, {"food": 100}, {"stone": 50})
    actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": True})
    for _ in range(2):
        engine.tick(CONFIG, state)
    assert state["offers"]["o0"]["status"] == trade.MOVING
    path = tmp_path / "mid.json.gz"
    snapshot.save(state, path)
    resumed = snapshot.load(path)
    for _ in range(40):
        engine.tick(CONFIG, state)
        engine.tick(CONFIG, resumed)
    assert state_hash(resumed) == state_hash(state)
    assert state["offers"]["o0"]["status"] == trade.DONE


def test_a_hungry_civ_doesnt_abandon_a_caravan_on_the_road(start):
    from fogline import ledger
    state = _pair(start)
    _offer(state, {"food": 100}, {"stone": 50})
    actions.dispatch(CONFIG, state, "saltreach", {"kind": "respond_trade", "offer": "o0", "accept": True})
    engine.tick(CONFIG, state)  # the legs set off with their cargo
    caravan = state["offers"]["o0"]["caravans"]["give"][0]
    stocks = state["civs"]["verdance"]["stocks"]
    ledger.apply(stocks, state["ledger"], None, "verdance", "food", -stocks["food"], ledger.Rule.EATING, state["tick"])
    units.pay_upkeep(CONFIG, state, "verdance", None)
    assert caravan in state["units"] and state["units"][caravan]["cargo"]  # unfed, not disbanded
    _assert_conserved(state)
    _run_until_done(state, "o0")
