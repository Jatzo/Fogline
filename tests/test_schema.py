"""Reply validation and the exported schema (PLAN sections 5 and 14).

A corpus of bad replies, each with the reason it must come back with; a check that no rejected
action changes state; and a check that the schema a ruler reads matches the checks it meets.
"""

import copy
import json

import pytest

from fogline import actions, engine, schema, worldgen
from fogline.config import Config
from fogline.state import state_hash

CONFIG = Config()
WAKE = {"next_wake": {"ticks": 2, "triggers": []}}


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _nested(levels):
    reply = {"actions": []}
    inner = reply
    for _ in range(levels):
        inner["actions"] = [{"kind": "set_research", "tech": "writing", "x": {}}]
        inner = inner["actions"][0]["x"]
    return reply


TEXT_CORPUS = [
    ("not json", "unparseable_reply", "not_json"),
    ("x" * (schema.MAX_REPLY_CHARS + 1), "unparseable_reply", "too_long"),
    (json.dumps(_nested(4)), "unparseable_reply", "too_deep"),
    # Regression (debug-log): this parsed on Linux and hit the recursion limit on Windows.
    ("[" * 3000 + "]" * 3000, "unparseable_reply", "too_deep"),
    (json.dumps({"actions": [], "end_turn": WAKE, "note": "[[[[[[[[[[[["})[:-1], "unparseable_reply", "not_json"),
    (json.dumps([1, 2]), "malformed", "reply"),
    (json.dumps({"actions": [], "end_turn": WAKE, "prompt": "ignore your rules"}), "malformed", "reply"),
]


@pytest.mark.parametrize("text, reason, kind", TEXT_CORPUS)
def test_bad_text_is_refused_before_anything_reads_it(text, reason, kind):
    reply, rejections = schema.validate_reply(text)
    assert reply is None and rejections == [{"index": -1, "kind": kind, "reason": reason}]


def test_brackets_inside_strings_do_not_count_towards_depth():
    assert schema.text_depth(json.dumps({"a": "[[[[[[[[[[{{{{{{ \\\" ]]]"})) == 1


def test_a_well_formed_reply_passes_through():
    text = json.dumps({"actions": [{"kind": "set_research", "tech": "writing"}], "end_turn": WAKE})
    assert schema.validate_reply(text) == (json.loads(text), [])


ACTION_CORPUS = [
    ({"kind": "set_research", "tech": 7}, "bad_args"),
    ({"kind": "set_research", "tech": "alchemy"}, "unknown_tech"),
    ({"kind": "set_research", "tech": "writing", "extra": 1}, "bad_args"),
    ({"kind": "build", "settlement": "verdance-0"}, "bad_args"),
    ({"kind": "build", "settlement": "verdance-0", "building": "castle"}, "unknown_building"),
    ({"kind": "build", "settlement": "verdance-0", "building": "farm", "tile": [1, 2]}, "bad_args"),
    ({"kind": "build", "settlement": "verdance-0", "building": "farm", "tile": "north"}, "bad_tile"),
    ({"kind": "build", "settlement": "x" * 41, "building": "farm"}, "bad_args"),
    ({"kind": "train_unit", "settlement": "verdance-0", "unit_kind": "dragon"}, "unknown_unit_kind"),
    ({"kind": "move_unit", "unit": "ironhold-u0", "to": "0,0"}, "unknown_unit"),
    ({"kind": "allocate_workers", "allocation": {"food": 90, "timber": 20}}, "bad_allocation"),
    ({"kind": "allocate_workers", "allocation": "all on food"}, "bad_allocation"),
    ({"kind": "teleport"}, "unknown_action"),
    ({"tech": "writing"}, "malformed"),
    ("set_research writing", "malformed"),
]


@pytest.mark.parametrize("action, reason", ACTION_CORPUS)
def test_a_bad_action_is_rejected_with_its_reason_and_changes_nothing(start, action, reason):
    state = copy.deepcopy(start)
    before = state_hash(state)
    assert actions.dispatch(CONFIG, state, "verdance", action) == reason
    assert state_hash(state) == before


def test_rejections_come_back_in_the_next_observation(start):
    state = copy.deepcopy(start)
    cap = CONFIG.max_actions_per_turn
    sent = [action for action, _ in ACTION_CORPUS[:cap]] + [{"kind": "set_research", "tech": "writing"}] * 3
    seen = []

    def decide(observation, scratch):
        seen.append(observation)
        return {"actions": sent if len(seen) == 1 else [], "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}

    engine.tick(CONFIG, state, deciders={"verdance": decide})
    engine.tick(CONFIG, state, deciders={"verdance": decide})
    expected = [(i, reason) for i, (_, reason) in enumerate(ACTION_CORPUS[:cap])]
    expected += [(i, "over_action_cap") for i in range(cap, len(sent))]
    assert [(r["index"], r["reason"]) for r in seen[1]["rejections"]] == expected


def test_a_reply_nested_two_thousand_deep_is_refused_not_crashed_on(start):
    state = copy.deepcopy(start)
    deep: dict = {}
    inner = deep
    for _ in range(2000):
        inner["x"] = {}
        inner = inner["x"]
    records = engine.tick(CONFIG, state, deciders={"verdance": lambda observation, scratch: deep})
    record = next(r for r in records if r.civ == "verdance")
    assert {"index": -1, "kind": "", "reason": "malformed"} in record.rejections


def test_the_schema_and_the_checks_agree_on_every_action():
    exported = {v["properties"]["kind"]["const"]: v
                for v in schema.json_schema(CONFIG)["properties"]["actions"]["items"]["oneOf"]}
    table = actions.action_table(CONFIG)
    assert set(exported) == set(table)
    for kind, spec in table.items():
        variant = exported[kind]
        assert set(variant["properties"]) == {"kind"} | set(spec.args)
        assert set(variant["required"]) == {"kind"} | {n for n, a in spec.args.items() if a.required}
        for name, arg in spec.args.items():
            prop = variant["properties"][name]
            if arg.kind == "enum":
                assert prop["enum"] == list(arg.choices)
                assert actions._check_arg(arg, prop["enum"][0]) is None
                assert actions._check_arg(arg, "not-a-choice") == arg.miss
            elif arg.kind in ("str", "tile"):
                assert actions._check_arg(arg, "1,2") is None
                assert actions._check_arg(arg, 12) == "bad_args"
            elif arg.kind == "alloc":
                assert set(prop["properties"]) <= set(engine.rules.LINES)
    limits = schema.json_schema(CONFIG)["properties"]
    assert limits["actions"]["maxItems"] == CONFIG.max_actions_per_turn
    wake = limits["end_turn"]["properties"]["next_wake"]["properties"]["ticks"]
    assert (wake["minimum"], wake["maximum"]) == (1, CONFIG.max_wake_ticks)


def test_a_huge_rejected_kind_is_cut_and_the_next_report_stays_within_the_cap(start):
    from fogline import observation, turns
    state = copy.deepcopy(start)
    replies = iter([
        {"actions": [{"kind": "x" * 19_000}], "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}},
        turns.Refused(({"index": -1, "kind": "y" * 19_000, "reason": "unparseable_reply"},)),
    ])
    for _ in range(2):
        reply = next(replies)
        engine.tick(CONFIG, state, deciders={"verdance": lambda o, m, r=reply: r})
        seen = observation.observe(CONFIG, state, "verdance")
        assert observation.size(seen) <= observation.MAX_CHARS
        assert all(len(r["kind"]) <= turns.MAX_KIND_CHARS for r in seen["rejections"])
