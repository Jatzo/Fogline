"""Step 1: wakes, the action path, the cap, the skip and standing orders (rules 16 and 21)."""

import copy
import dataclasses

import pytest

from fogline import actions, bots, engine, observation, turns, worldgen
from fogline.config import Config
from fogline.state import parse_tile_key, state_hash, tile_key
from test_construction import _free_footprint_tile
from test_engine import _assert_conserved

CONFIG = dataclasses.replace(Config(), events_enabled=False)
NOTHING = {"actions": [], "end_turn": {"next_wake": {"ticks": 8, "triggers": []}}}


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    return copy.deepcopy(start)


def _scripted(replies, calls):
    """A decider that hands back canned replies in order, noting each brief it was given."""
    def decide(brief, scratch):
        calls.append(brief)
        return copy.deepcopy(replies[min(len(calls), len(replies)) - 1])
    return decide


def _record_of(records, civ_id):
    return next(r for r in records if r.civ == civ_id)


BAD = {"actions": [{"kind": "build", "settlement": "nowhere", "building": "farm"}],
       "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}
EMPTY = {"actions": [], "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}


def test_three_wholly_invalid_turns_skip_the_next(start):
    state = _fresh(start)
    calls = []
    for _ in range(5):
        engine.tick(CONFIG, state, deciders={"ironhold": _scripted([BAD], calls)})
    assert [b["tick"] for b in calls] == [0, 1, 2, 4]
    assert calls[1]["rejections"] == [{"index": 0, "kind": "build", "reason": "not_own_settlement"}]
    skipped = [e["tick"] for e in state["events"] if e["kind"] == "turn_skipped" and e["civ"] == "ironhold"]
    assert skipped == [3]


def test_garbled_replies_count_as_invalid_turns(start):
    state = _fresh(start)
    calls = []
    garbled = [{"actions": "attack", "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}, "nonsense"]
    for _ in range(5):
        engine.tick(CONFIG, state, deciders={"ironhold": _scripted(garbled, calls)})
    assert [b["tick"] for b in calls] == [0, 1, 2, 4]


def test_an_empty_turn_resets_the_invalid_streak(start):
    state = _fresh(start)
    calls = []
    decider = _scripted([BAD, BAD, EMPTY, BAD, BAD, BAD], calls)
    for _ in range(6):
        engine.tick(CONFIG, state, deciders={"ironhold": decider})
    assert [b["tick"] for b in calls] == [0, 1, 2, 3, 4, 5]


def test_only_twelve_actions_are_read_per_turn(start):
    state = _fresh(start)
    many = {"actions": [{"kind": "allocate_workers", "allocation": {"food": 100}}] * 13,
            "end_turn": {"next_wake": {"ticks": 8, "triggers": []}}}
    record = _record_of(engine.tick(CONFIG, state, deciders={"verdance": lambda brief, scratch: many}), "verdance")
    assert list(record.rejections) == [{"index": 12, "kind": "allocate_workers", "reason": "over_action_cap"}]


def test_dispatch_checks_the_shape_and_turns_relative_tiles_into_map_tiles(start):
    state = _fresh(start)
    dispatch = actions.dispatch
    assert dispatch(CONFIG, state, "verdance", "build") == "malformed"
    assert dispatch(CONFIG, state, "verdance", {"kind": "teleport"}) == "unknown_action"
    assert dispatch(CONFIG, state, "verdance", {"kind": "set_research", "tech": "writing", "x": 1}) == "bad_args"
    assert dispatch(CONFIG, state, "verdance", {"kind": "set_research"}) == "bad_args"
    assert dispatch(CONFIG, state, "verdance", {"kind": "set_research", "tech": 7}) == "bad_args"
    assert dispatch(CONFIG, state, "verdance", {"kind": "move_unit", "unit": "verdance-u0", "to": "north"}) \
        == "bad_tile"
    hint = _free_footprint_tile(state, "verdance-0")
    ox, oy = parse_tile_key(state["civs"]["verdance"]["origin"])
    x, y = parse_tile_key(hint)
    relative = tile_key(x - ox, y - oy)
    assert dispatch(CONFIG, state, "verdance",
                    {"kind": "build", "settlement": "verdance-0", "building": "housing", "tile": relative}) is None
    assert state["civs"]["verdance"]["build_queue"][-1]["hint"] == hint


def test_a_sleeping_civ_wakes_on_its_heartbeat(start):
    state = _fresh(start)
    calls = []
    engine.run(CONFIG, state, 13, deciders={"frostmark": _scripted([NOTHING], calls)})
    assert [b["tick"] for b in calls] == [0, 6, 12]
    assert {"trigger": "heartbeat", "detail": ""} in calls[1]["triggers"]


def test_a_subscribed_trigger_wakes_the_civ_the_next_tick(start):
    state = _fresh(start)
    calls = []
    first = {"actions": [{"kind": "build", "settlement": "verdance-1", "building": "housing"}],
             "end_turn": {"next_wake": {"ticks": 8, "triggers": ["build_done"]}}}
    later = {"actions": [], "end_turn": {"next_wake": {"ticks": 8, "triggers": ["build_done"]}}}
    engine.run(CONFIG, state, 3, deciders={"verdance": _scripted([first, later], calls)})
    assert [b["tick"] for b in calls] == [0, 1]
    assert any(t["trigger"] == "build_done" and t["detail"].startswith("new housing at ") for t in calls[1]["triggers"])


def test_a_skipped_turn_keeps_its_triggers(start):
    state = _fresh(start)
    calls = []
    state["civs"]["verdance"]["turn"]["skip_next"] = True
    actions.build(CONFIG, state, "verdance", "verdance-1", "housing")  # finishes during tick 0
    engine.run(CONFIG, state, 2, deciders={"verdance": _scripted([NOTHING], calls)})
    assert [b["tick"] for b in calls] == [1]
    assert any(t["trigger"] == "build_done" and t["detail"].startswith("new housing at ") for t in calls[0]["triggers"])


def test_a_bad_end_turn_is_rejected_and_the_civ_is_asked_again(start):
    state = _fresh(start)
    calls = []
    broken = {"actions": [], "end_turn": {"next_wake": {"ticks": 99}}}
    records = engine.run(CONFIG, state, 2, deciders={"saltreach": _scripted([broken], calls)})
    assert [b["tick"] for b in calls] == [0, 1]
    assert {"index": -1, "kind": "end_turn", "reason": "bad_end_turn"} in _record_of(records, "saltreach").rejections


def test_bot_memory_is_kept_and_bad_memory_refused(start):
    state = _fresh(start)

    def counter(brief, scratch):
        count = scratch.get("n", 0)
        return {**EMPTY, "memory": {"n": count + 1}}

    engine.run(CONFIG, state, 3, deciders={"ironhold": counter})
    assert state["civs"]["ironhold"]["bot_memory"] == {"n": 3}
    records = engine.tick(CONFIG, state, deciders={"ironhold": lambda b, m: {**EMPTY, "memory": {"x": 1.5}}})
    record = _record_of(records, "ironhold")
    assert {"index": -1, "kind": "memory", "reason": "bad_memory"} in record.rejections
    assert state["civs"]["ironhold"]["bot_memory"] == {"n": 3}


def test_a_stock_threshold_wakes_once_on_the_way_down(start):
    state = _fresh(start)
    calls = []
    watch = {"actions": [], "end_turn": {"next_wake": {"ticks": 8, "triggers": ["stock_below_threshold"]},
                                         "reorders": [{"stock": "food", "below": 100000, "workers": 2}]}}
    engine.run(CONFIG, state, 3, deciders={"verdance": _scripted([watch], calls)})
    assert state["civs"]["verdance"]["reorders"] == [{"stock": "food", "below": 100000, "workers": 2}]
    assert [b["tick"] for b in calls] == [0, 1]
    assert {"trigger": "stock_below_threshold", "detail": "food"} in calls[1]["triggers"]


def test_spiral_scout_runs_are_deterministic_and_conserved():
    def play():
        state = worldgen.generate(CONFIG, 2)
        engine.run(CONFIG, state, 100, deciders={civ: bots.spiral_scout for civ in state["civs"]})
        return state

    first, second = play(), play()
    assert state_hash(first) == state_hash(second)
    _assert_conserved(first)
    assert all(c["bot_memory"].get("leg", 0) > 0 for c in first["civs"].values())


def test_the_trigger_table_only_names_real_triggers():
    assert set(turns.EVENT_TRIGGERS.values()) <= set(turns.Trigger)
    assert turns.ALWAYS_ON <= set(turns.Trigger)


def test_the_builder_puts_a_new_farm_where_people_lack_work_not_in_its_town(start):
    # Regression (docs/debug-log.md): seed 1 Verdance piled 32 farms on a 21-person town while its
    # 159-person capital had 4, so the civ ran short of food and every settlement stopped growing.
    brief = observation.observe(CONFIG, _fresh(start), "verdance")
    capital, town = brief["settlements"][0], brief["settlements"][3]
    capital.update(pop=159, buildings=["housing"] * 20 + ["farm"] * 4 + ["lumber_camp", "mine", "workshop"])
    town.update(pop=21, buildings=["housing"] * 3 + ["farm"] * 32)
    scratch = {"town": town["id"], "history": [[brief["tick"] - 4, 10_000, 300, 200, 110]]}
    reply = bots.make_builder(CONFIG)(brief, scratch)
    farms = [a["settlement"] for a in reply["actions"] if a["kind"] == "build" and a["building"] == "farm"]
    assert farms == [capital["id"]]
