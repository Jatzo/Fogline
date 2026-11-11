"""The contact surface (Phase 3 M15): reputation, met civs as words, widened triggers, unmet
names, tech catch-up and offers."""

import copy

import pytest

from fogline import actions, engine, observation, prompts, reputation, techs, worldgen
from fogline.config import Config

CONFIG = Config()


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _meet(state, a, b):
    state["civs"][a]["met"][b] = state["tick"]
    state["civs"][b]["met"][a] = state["tick"]


def test_every_civ_starts_with_the_rules_view_of_each_other(start):
    views = start["reputation"]
    assert all(views[a][b] == reputation.start(CONFIG, b) for a in views for b in views[a])
    assert [reputation.start(CONFIG, c) for c in ("verdance", "saltreach", "frostmark", "ironhold", "dunerunners")] \
        == [13, 2, 2, -1, -11]  # rules 11


@pytest.mark.parametrize("value, word", [(100, "trusted"), (60, "trusted"), (59, "friendly"), (20, "friendly"),
                                         (19, "unknown"), (-19, "unknown"), (-20, "wary"), (-59, "wary"),
                                         (-60, "hostile"), (-100, "hostile")])
def test_a_view_reads_as_its_word(value, word):
    assert reputation.word(value) == word


def test_a_view_drifts_one_point_back_every_four_ticks(start):
    state = copy.deepcopy(start)
    reputation.change(state, "ironhold", "verdance", 10)
    home = reputation.start(CONFIG, "verdance")
    seen = []
    for _ in range(9):
        engine.tick(CONFIG, state)
        seen.append(state["reputation"]["ironhold"]["verdance"])
    assert seen == [home + 10] * 4 + [home + 9] * 4 + [home + 8]


def test_a_met_civ_shows_as_a_word_never_a_number(start):
    state = copy.deepcopy(start)
    _meet(state, "verdance", "ironhold")
    reputation.change(state, "verdance", "ironhold", 40)
    seen = observation.observe(CONFIG, state, "verdance")
    assert seen["met"] == [{"name": "Ironhold", "standing": "friendly"}]
    assert str(state["reputation"]["verdance"]["ironhold"]) not in str(seen["met"])


def test_a_trigger_naming_an_unmet_civ_is_dropped_whole(start):
    state = copy.deepcopy(start)
    raised = [{"trigger": "foreign_unit_sighted", "detail": "(ironhold-u0)."}, {"trigger": "timer", "detail": ""}]
    assert observation.observe(CONFIG, state, "verdance", raised)["triggers"] == [{"trigger": "timer", "detail": ""}]
    _meet(state, "verdance", "ironhold")
    shown = observation.observe(CONFIG, state, "verdance", raised)["triggers"]
    assert shown[0] == {"trigger": "foreign_unit_sighted", "detail": "(Ironhold)."}


def test_an_unmet_civ_answers_like_a_made_up_one(start):
    state = copy.deepcopy(start)
    assert actions.met_civ(CONFIG, state, "verdance", "Ironhold") is None
    assert actions.met_civ(CONFIG, state, "verdance", "Atlantis") is None
    _meet(state, "verdance", "ironhold")
    assert actions.met_civ(CONFIG, state, "verdance", " ironhold ") == "ironhold"
    assert actions.met_civ(CONFIG, state, "verdance", 7) is None


def test_the_schema_widens_only_after_contact():
    alone, met = prompts.system_prompt(CONFIG, "verdance"), prompts.system_prompt(CONFIG, "verdance", met=True)
    for trigger in ("message_received", "offer_received", "offer_expiring", "foreign_unit_sighted"):
        assert trigger not in alone and trigger in met
    assert '"contact"' not in met  # always on, so never offered


def test_a_tech_a_met_civ_holds_costs_a_quarter_less(start):
    state = copy.deepcopy(start)
    full, _ = techs.cost(CONFIG, "writing")
    state["civs"]["ironhold"]["techs"].append("writing")
    assert techs.points(CONFIG, state, "verdance", "writing") == full  # not met yet
    _meet(state, "verdance", "ironhold")
    assert techs.points(CONFIG, state, "verdance", "writing") == full * 3 // 4


def test_every_offered_tech_has_a_hint_and_gated_ones_stay_hidden(start):
    state = copy.deepcopy(start)
    offered = observation.observe(CONFIG, state, "verdance")["research"]["available"]
    assert offered and all(o["hint"] == techs.HINTS[o["tech"]] for o in offered)
    for civ_id in sorted(state["civs"]):
        civ = state["civs"][civ_id]
        civ["techs"] = sorted(set(civ["techs"]) | {"woodworking", "quarrying", "masonry"})
        names = [o["tech"] for o in observation.observe(CONFIG, state, civ_id)["research"]["available"]]
        assert ("harbours" in names) == techs.gate_met(state, civ_id, "coast"), civ_id
