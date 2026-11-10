"""Tech tree shape, set_research checks, and the research pool (rules 14, ADR 0002)."""

import copy
import dataclasses

import pytest

from fogline import actions, engine, ledger, techs, worldgen
from fogline.config import Config

CONFIG = dataclasses.replace(Config(), events_enabled=False)


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    state = copy.deepcopy(start)
    # No workshops means no scholars, so the pool only moves when a test moves it.
    for settlement in state["settlements"].values():
        settlement["buildings"] = [b for b in settlement["buildings"] if b["type"] != "workshop"]
    return state


def test_the_tree_has_21_nodes_and_4040_points():
    assert len(techs.TECHS) == 21
    assert sum(1 for t in techs.TECHS.values() if t.era == 0) == 4
    assert sum(techs.cost(CONFIG, t)[0] for t, spec in techs.TECHS.items() if spec.era) == 4040


def test_every_prerequisite_exists_and_comes_from_an_earlier_era():
    for tech_id, tech in techs.TECHS.items():
        for need in tech.needs:
            assert techs.TECHS[need].era < tech.era, (tech_id, need)


def test_tech_speed_scales_points_not_resources():
    slow = dataclasses.replace(CONFIG, tech_speed=1500)
    assert techs.cost(slow, "writing") == (120, {"timber": 20})


def test_set_research_reason_codes(start):
    state = _fresh(start)
    civ_id = "verdance"
    assert actions.set_research(CONFIG, state, civ_id, "gunpowder") == "unknown_tech"
    assert actions.set_research(CONFIG, state, civ_id, "farming") == "already_known"
    assert actions.set_research(CONFIG, state, civ_id, "iron_working") == "prereqs_missing"
    state["civs"][civ_id]["techs"].append("quarrying")
    for node_id in [n for n, node in state["nodes"].items() if node["kind"] == "metal"]:
        del state["nodes"][node_id]  # no metal anywhere: the gate can't be met
    assert actions.set_research(CONFIG, state, civ_id, "iron_working") == "gate_unmet"
    assert state["civs"][civ_id]["research"]["tech"] == ""
    assert actions.set_research(CONFIG, state, civ_id, "writing") is None
    assert state["civs"][civ_id]["research"]["tech"] == "writing"


def test_a_tech_completes_when_the_pool_covers_it_and_is_paid_once(start):
    state = _fresh(start)
    civ = state["civs"]["verdance"]
    actions.set_research(CONFIG, state, "verdance", "crop_rotation")
    civ["research"]["points_milli"] = 80_000
    engine.tick(CONFIG, state)
    assert "crop_rotation" in civ["techs"]
    assert civ["research"] == {"tech": "", "points_milli": 0}
    assert state["ledger"]["verdance:timber:research_cost"] == -20


def test_a_finished_but_unpaid_tech_waits_with_its_points(start):
    state = _fresh(start)
    civ = state["civs"]["saltreach"]
    ledger.apply(civ["stocks"], state["ledger"], None, "saltreach", "timber", -civ["stocks"]["timber"],
                 ledger.Rule.RIOT, 0)
    actions.set_research(CONFIG, state, "saltreach", "writing")
    civ["research"]["points_milli"] = 90_000
    engine.tick(CONFIG, state)
    assert "writing" not in civ["techs"]
    assert civ["research"]["points_milli"] == 90_000


def test_points_with_no_tech_are_lost_until_the_tree_is_done(start):
    state = _fresh(start)
    civ = state["civs"]["frostmark"]
    civ["research"]["points_milli"] = 5_500
    engine.tick(CONFIG, state)
    assert civ["research"]["points_milli"] == 0 and civ["prestige"] == 0
    civ["techs"] = list(techs.TECHS)
    civ["research"]["points_milli"] = 5_500
    engine.tick(CONFIG, state)
    assert civ["prestige"] == 5 and civ["research"]["points_milli"] == 500


def test_a_printing_house_multiplies_research_by_one_and_a_half(start):
    def points_after_one_tick(with_house):
        state = copy.deepcopy(start)
        capital = state["settlements"]["ironhold-0"]
        capital["workers"] = {}
        if with_house:
            capital["buildings"].append({"type": "printing_house", "tile": "0,0", "built_tick": 0, "owed": False,
                                         "arrears_ticks": 0, "damaged": False, "ruin": False})
        actions.set_research(CONFIG, state, "ironhold", "writing")
        engine.tick(CONFIG, state)
        return state["civs"]["ironhold"]["research"]["points_milli"]

    plain, printed = points_after_one_tick(False), points_after_one_tick(True)
    assert plain > 0 and printed == plain * 1500 // 1000
