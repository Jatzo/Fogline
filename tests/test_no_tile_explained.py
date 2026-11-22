"""A no_tile build refusal says why (ADR 0015). Over 400 ticks of seed 1, Saltreach asked for a lumber
camp 21 times and got a bare no_tile each time: its one forest node was used up and built on, and its
other settlements had none. The detail states what the building needs and where the civ has room,
from the civ's own land only."""

import copy
import dataclasses

import pytest

from fogline import layout, observation, turns, worldgen
from fogline.config import Config
from fogline.construction import MAX_NO_TILE_CHARS
from fogline.state import parse_tile_key, state_hash

CONFIG = dataclasses.replace(Config(), events_enabled=False)
CIV = "saltreach"
CAPITAL = "saltreach-0"


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _without_forest(start):
    """Saltreach with lumber camps unlocked and every forest node in its land used up."""
    state = copy.deepcopy(start)
    state["civs"][CIV]["techs"].append(CONFIG.buildings["lumber_camp"]["tech"])
    for node in state["nodes"].values():
        owner = state["territory"].get(node["tile"])
        if node["kind"] == "forest" and owner and state["settlements"][owner]["civ"] == CIV:
            node["node"] = 0
    return state


def _refusals(state, actions):
    reply = {"actions": actions, "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}
    turns.step(CONFIG, state, {CIV: lambda brief, scratch: copy.deepcopy(reply)}, None)
    return state["civs"][CIV]["turn"]["rejections"]


def _foreign_forest_tile(state):
    return next(n["tile"] for n in sorted(state["nodes"].values(), key=lambda n: n["tile"])
                if n["kind"] == "forest" and state["territory"].get(n["tile"])
                and state["settlements"][state["territory"][n["tile"]]]["civ"] != CIV)


def test_a_lumber_camp_with_no_forest_left_is_refused_with_the_reason(start):
    state = _without_forest(start)
    [refusal] = _refusals(state, [{"kind": "build", "settlement": CAPITAL, "building": "lumber_camp"}])
    assert refusal["reason"] == "no_tile"
    name = state["settlements"][CAPITAL]["name"]
    assert f"{name}'s forest node at" in refusal["detail"] and "used up" in refusal["detail"]
    assert refusal["detail"].endswith("None of your settlements has room for a lumber_camp.")
    assert len(refusal["detail"]) <= MAX_NO_TILE_CHARS


def test_a_settlement_of_the_civ_with_room_is_named(start):
    state = _without_forest(start)
    other = "saltreach-2"
    centre = parse_tile_key(state["settlements"][other]["tile"])
    radius = layout.STAGE_RADIUS[state["settlements"][other]["stage"]]
    taken = layout.occupied_tiles(state) | layout.node_tiles(state)
    tile = next(t for t in sorted(state["territory"])
                if state["territory"][t] == other and t not in taken
                and layout.is_land(state["map"], *parse_tile_key(t))
                and max(abs(a - b) for a, b in zip(parse_tile_key(t), centre)) <= radius)
    state["nodes"]["test-forest"] = {"finite": True, "home": "", "kind": "forest", "node": 100, "regrowth": 0,
                                     "size": 100, "small": False, "tile": tile}
    [refusal] = _refusals(state, [{"kind": "build", "settlement": CAPITAL, "building": "lumber_camp"}])
    name = state["settlements"][other]["name"]
    assert refusal["detail"].endswith(f"Your settlements with room for a lumber_camp: {name}.")


def test_a_hint_off_own_land_says_only_that(start):
    state = _without_forest(start)
    tile = _foreign_forest_tile(state)
    shown = observation.relative(state, CIV, tile)
    [refusal] = _refusals(state, [{"kind": "build", "settlement": CAPITAL, "building": "lumber_camp",
                                   "tile": shown}])
    first, _, rest = refusal["detail"].partition(". ")
    assert first == f"Tile {shown} is not in your territory"
    assert shown not in rest  # nothing more is said about a tile the civ doesn't hold


def test_the_detail_never_names_another_civ(start):
    state = _without_forest(start)
    [refusal] = _refusals(state, [{"kind": "build", "settlement": CAPITAL, "building": "lumber_camp",
                                   "tile": observation.relative(state, CIV, _foreign_forest_tile(state))}])
    others = {sid for sid, s in state["settlements"].items() if s["civ"] != CIV}
    text = refusal["detail"].lower()
    assert not any(state["settlements"][sid]["name"].lower() in text for sid in others)
    assert not any(civ in text for civ in state["civs"] if civ != CIV)


def test_other_refusals_carry_no_detail_and_both_shapes_pass_the_observation_check(start):
    state = _without_forest(start)
    rejections = _refusals(state, [{"kind": "build", "settlement": "nowhere", "building": "farm"},
                                   {"kind": "build", "settlement": CAPITAL, "building": "lumber_camp"}])
    assert [("detail" in r) for r in rejections] == [False, True]
    observation.check_fields(observation.observe(CONFIG, state, CIV))


def test_the_same_refusal_leaves_the_same_world(start):
    """The detail is kept with the turn, so a replayed run must write it identically."""
    action = [{"kind": "build", "settlement": CAPITAL, "building": "lumber_camp"}]
    first, second = _without_forest(start), _without_forest(start)
    _refusals(first, action)
    _refusals(second, action)
    assert state_hash(first) == state_hash(second)
