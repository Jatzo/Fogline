"""Trade made legible to rulers (ADR 0014). Three live runs refused 70 to 92% of offers as
no_caravan: rulers weren't told an offer needs a free caravan, saw a held caravan as ready, and a civ
out of timber couldn't build the caravan that would bring timber in."""

import copy
import hashlib
import json

import pytest

from fogline import actions, observation, prompts, schema, units, worldgen
from fogline.config import Config
from test_trade import _offer, _pair

CONFIG = Config()
CIVS = ("dunerunners", "frostmark", "ironhold", "saltreach", "verdance")

# sha256 of each civ's system prompt and of the reply schema before contact, taken at commit 9cfca95,
# before trade was described. Nothing about trade may reach a ruler before it has met anyone.
BEFORE_CONTACT = {
    "dunerunners": "3767d074ddf0d1e55b041fd054cf1d7d7eeef76ce5e28f2e9f8a15afb9070427",
    "frostmark": "bdb4d5248157ee6cbb3c59adb40f0bfd2889e2b07c70ed0bfff021051c1a6d4d",
    "ironhold": "6747638f13e9a08797ac04632055fde46fbef14114805726baf4897cdef3634c",
    "saltreach": "a13bef94f55ad7af486d385a7c742ce186b8c085e8585b0437d9a424fa51c7b3",
    "verdance": "2f75c1264de7b7256221b4ebe4af618f32575c2267e2e0037f125c752a35dc4e",
    "schema": "c4c5b2589b13a8c769cc0e1e317ba8f9dc253dd0cea82a837f023ff52c364cdd",
}


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def test_before_contact_the_prompt_and_schema_are_byte_for_byte_unchanged():
    for civ in CIVS:
        assert _sha(prompts.system_prompt(CONFIG, civ)) == BEFORE_CONTACT[civ], civ
    assert _sha(json.dumps(schema.json_schema(CONFIG), sort_keys=True)) == BEFORE_CONTACT["schema"]


def test_after_contact_the_schema_explains_caravans():
    variants = schema.json_schema(CONFIG, ["Saltreach"])["properties"]["actions"]["items"]["oneOf"]
    described = {v["properties"]["kind"]["const"]: v.get("description", "") for v in variants}
    assert "one free caravan of yours for every 100 goods you give (200 once you know Carts)" in described["offer_trade"]
    assert "reserved: true" in described["offer_trade"]
    assert "open offer made to you" in described["respond_trade"]
    assert "10 food and 20 timber, or 10 food and 20 stone" in described["train_unit"]


def _caravan(state, civ_id):
    seen = observation.observe(CONFIG, state, civ_id)
    return [u for u in seen["units"] if u["kind"] == "caravan"]


def test_a_caravan_shows_reserved_while_an_offer_holds_it(start):
    state = _pair(start)
    assert [u["reserved"] for u in _caravan(state, "verdance")] == [False]
    assert _offer(state, {"food": 50}, {"stone": 10}) is None
    assert [u["reserved"] for u in _caravan(state, "verdance")] == [True]
    offer_id = next(iter(state["offers"]))
    assert actions.dispatch(CONFIG, state, "saltreach",
                            {"kind": "respond_trade", "offer": offer_id, "accept": False}) is None
    assert [u["reserved"] for u in _caravan(state, "verdance")] == [False]


def test_other_units_carry_no_reserved_flag(start):
    seen = observation.observe(CONFIG, copy.deepcopy(start), "verdance")
    assert seen["units"] and all("reserved" not in u for u in seen["units"])


def _train(state, civ_id):
    return actions.dispatch(CONFIG, state, civ_id, {"kind": "train_unit", "settlement": f"{civ_id}-0",
                                                    "unit_kind": "caravan"})


def test_a_caravan_is_paid_in_timber_when_the_civ_has_it(start):
    state = _pair(start, caravans=0)
    before = dict(state["civs"]["saltreach"]["stocks"])
    assert _train(state, "saltreach") is None
    after = state["civs"]["saltreach"]["stocks"]
    assert (before["timber"] - after["timber"], before["stone"] - after["stone"]) == (20, 0)


def test_a_civ_out_of_timber_pays_for_a_caravan_in_stone(start):
    state = _pair(start, caravans=0)
    stocks = state["civs"]["saltreach"]["stocks"]
    stocks["timber"] = 19
    before = dict(stocks)
    assert _train(state, "saltreach") is None
    assert (before["timber"] - stocks["timber"], before["stone"] - stocks["stone"],
            before["food"] - stocks["food"]) == (0, 20, 10)


def test_a_civ_short_of_both_still_cannot_afford_one(start):
    state = _pair(start, caravans=0)
    stocks = state["civs"]["saltreach"]["stocks"]
    stocks["timber"], stocks["stone"] = 19, 19
    assert _train(state, "saltreach") == actions.Reason.CANNOT_AFFORD


def test_before_contact_a_caravan_is_still_an_unknown_unit_whatever_the_stocks(start):
    state = copy.deepcopy(start)
    state["civs"]["saltreach"]["stocks"]["timber"] = 0
    assert _train(state, "saltreach") == actions.Reason.UNKNOWN_UNIT_KIND
