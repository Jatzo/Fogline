"""Rulers may name their own settlements where an action wants an id (llm.settlement_ids).

Three live runs lost about 370 build orders to "Tidewatch" written for "saltreach-2". The swap reads
only the civ's own settlements from its observation, so it can't reveal anything about another civ."""

import json

from fogline import engine, llm, worldgen
from fogline.config import Config

CONFIG = Config()
OWN = {"settlements": [{"id": "saltreach-0", "name": "Brinehaven"}, {"id": "saltreach-2", "name": "Tidewatch"}]}


def _build(settlement):
    return {"actions": [{"kind": "build", "settlement": settlement, "building": "housing"}]}


def test_an_own_settlement_name_becomes_its_id_whatever_its_case():
    assert llm.settlement_ids(_build("Tidewatch"), OWN) == _build("saltreach-2")
    assert llm.settlement_ids(_build("tideWATCH"), OWN) == _build("saltreach-2")


def test_ids_foreign_names_and_made_up_names_pass_through_unchanged():
    for target in ("saltreach-0", "Thornwick", "Nowhere", "verdance-1"):
        assert llm.settlement_ids(_build(target), OWN) == _build(target)


def test_a_shared_name_or_a_name_that_is_also_an_id_is_left_alone():
    shared = {"settlements": [{"id": "a-0", "name": "Ford"}, {"id": "a-1", "name": "Ford"}]}
    assert llm.settlement_ids(_build("Ford"), shared) == _build("Ford")
    tricky = {"settlements": [{"id": "a-0", "name": "a-1"}, {"id": "a-1", "name": "Hill"}]}
    assert llm.settlement_ids(_build("a-1"), tricky) == _build("a-1")


def test_the_reply_it_was_given_is_not_changed():
    reply = _build("Tidewatch")
    llm.settlement_ids(reply, OWN)
    assert reply == _build("Tidewatch")


def _first_turn_rejections(civ, target_for):
    """Play two ticks with one ruler that builds housing in target_for(observation), and return
    the rejections it is shown on its second turn."""

    class Builder:
        def call(self, key, observation):
            reply = {**_build(target_for(observation)), "end_turn": {"next_wake": {"ticks": 1}}}
            return llm.Outcome(llm.OK, json.dumps(reply))

    state = worldgen.generate(CONFIG, 1)
    seen = []
    ruler = llm.make_ruler(Builder(), civ)

    def watching(observation, scratch):
        seen.append(observation)
        return ruler(observation, scratch)

    engine.run(CONFIG, state, 2, deciders={civ: watching})
    return seen[1]["rejections"]


def _own_name(observation):
    return observation["settlements"][0]["name"]


def test_the_engine_builds_where_the_ruler_named():
    assert _first_turn_rejections("verdance", _own_name) == []


def test_another_civs_settlement_name_is_refused_exactly_like_a_made_up_one():
    foreign_name = worldgen.generate(CONFIG, 1)["settlements"]["saltreach-0"]["name"]
    foreign = _first_turn_rejections("verdance", lambda o: foreign_name)
    made_up = _first_turn_rejections("verdance", lambda o: "Nowhere At All")
    assert foreign == made_up == [{"index": 0, "kind": "build", "reason": "not_own_settlement"}]
