"""The Phase 4 checks (PLAN section 15): contact timing with scripted scouts, and the report a
finished run is checked with (fogline/phase4.py)."""

import statistics
from collections import Counter

import pytest

from fogline import bots, engine, phase4, run, worldgen
from fogline.config import Config

CONFIG = Config()
CONTACT_WINDOW = (30, 60)  # rules 20: median first contact of scripted scouts, ticks 30 to 60
CONTACT_SEEDS = range(1, 11)


def _first_contact(seed, limit=120):
    state = worldgen.generate(CONFIG, seed)
    for _ in range(limit):
        engine.tick(CONFIG, state, deciders={c: bots.spiral_scout for c in state["civs"]})
        met = [tick for civ in state["civs"].values() for tick in civ["met"].values()]
        if met:
            return min(met)
    return None


def test_scripted_scouts_make_first_contact_inside_the_target_window():
    firsts = [_first_contact(seed) for seed in CONTACT_SEEDS]
    assert None not in firsts, firsts
    assert CONTACT_WINDOW[0] <= statistics.median(firsts) <= CONTACT_WINDOW[1], firsts


def test_jensen_shannon_is_zero_for_the_same_mix_and_one_for_mixes_with_nothing_in_common():
    same = Counter(build=2, move_unit=6)
    assert phase4.jensen_shannon(same, Counter(build=1, move_unit=3)) == 0
    assert phase4.jensen_shannon(Counter(build=4), Counter(move_unit=4)) == pytest.approx(1.0)
    assert 0 < phase4.jensen_shannon(same, Counter(build=6, move_unit=2)) < 1
    with pytest.raises(ValueError):
        phase4.jensen_shannon(same, Counter())


def test_only_actions_a_turn_carried_out_are_counted():
    reply = {"actions": [{"kind": "build"}, {"kind": "build"}, {"kind": "move_unit"}, {"kind": None}], "end_turn": {}}
    rejections = [{"index": 0, "kind": "build", "reason": "no_tile"}, {"index": 3, "kind": "", "reason": "bad_action"},
                  {"index": -1, "kind": "end_turn", "reason": "bad_end_turn"}]
    turn = {"step": "decide", "reply": reply, "rejections": rejections}
    assert phase4.applied_actions(turn) == Counter(build=1, move_unit=1)  # a kindless refusal costs only its own
    assert phase4.applied_actions({**turn, "reply": None}) == Counter()  # a reply that never parsed
    assert phase4.applied_actions({**turn, "step": "reflect"}) == Counter()


def test_building_types_come_from_the_civs_own_built_events():
    events = [{"kind": "built", "civ": "verdance", "detail": "new farm at 1,0"},
              {"kind": "built", "civ": "verdance", "detail": "new farm at 2,0"},
              {"kind": "built", "civ": "verdance", "detail": "upgrade housing at 0,0"},
              {"kind": "built", "civ": "ironhold", "detail": "new mine at 5,5"}]
    assert phase4.building_types(events, "verdance") == ["farm", "housing"]


def test_a_mock_run_is_checked_from_its_folder(tmp_path):
    out = tmp_path / "mock"
    run.play(CONFIG, 1, 42, out=out, mode="mock", llm_civs=["saltreach", "verdance"])
    result = phase4.check(out)
    assert result["tick"] == 42 and result["passed"]["reached_last_tick"]  # 42 isn't a snapshot tick
    assert set(result["pair_divergence"]) == {"saltreach verdance"} and result["divergence"] is not None
    assert result["civs"]["ironhold"]["actions"] is None and result["civs"]["verdance"]["actions"]
