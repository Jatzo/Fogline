"""The Phase 3b slice setup: placement, the cost meter, and a mock slice that replays."""

import dataclasses

import pytest

from fogline import engine, llm, run, units, worldgen
from fogline.config import Config
from fogline.state import state_hash

CONFIG = dataclasses.replace(Config(), slice_pair=run.SLICE_PAIR)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_slice_pair_meets_within_eight_ticks_whatever_its_rulers_do(seed):
    state = worldgen.generate(CONFIG, seed)
    for _ in range(8):
        if state["civs"]["verdance"]["met"]:
            break
        engine.tick(CONFIG, state)  # nobody decides anything
    assert "saltreach" in state["civs"]["verdance"]["met"] and "verdance" in state["civs"]["saltreach"]["met"]


def test_a_normal_world_is_untouched_by_the_slice_option():
    assert state_hash(worldgen.generate(Config(), 1)) != state_hash(worldgen.generate(CONFIG, 1))
    assert worldgen.generate(Config(), 1)["civs"]["verdance"]["met"] == {}


def test_the_cost_meter_splits_calls_and_cost_at_first_contact():
    state = worldgen.generate(Config(), 1)
    state["civs"]["verdance"]["met"]["ironhold"] = 40
    state["civs"]["verdance"]["first_contact_turn"] = 41  # met in tick 40's sight pass, after its turn
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
             "total_cost_usd": 0.01}
    rows = [{"civ": "verdance", "tick": t, "usage": usage} for t in (0, 10, 39, 40, 41, 90)]
    meter = run.cost_meter(rows, state, 0, 100)["verdance"]
    assert meter["first_contact"] == 40 and meter["first_contact_turn"] == 41
    before, after = meter["before_contact"], meter["after_contact"]
    assert (before["ticks"], before["calls"], after["ticks"], after["calls"]) == (41, 4, 59, 2)
    assert before["input_tokens"] == 40 and after["cost_usd"] == 0.02


def test_contact_in_a_tick_is_first_seen_by_the_next_turn_and_at_setup_by_turn_zero():
    state = worldgen.generate(Config(), 1)
    engine.tick(Config(), state)
    uid = units.spawn(Config(), state, "verdance", "scout", "verdance-0", None, pay=False, ready_now=True)
    state["units"][uid]["tile"] = state["settlements"]["saltreach-0"]["tile"]  # standing in their capital
    engine.tick(Config(), state)
    assert state["civs"]["verdance"]["met"]["saltreach"] == 1
    assert state["civs"]["verdance"]["first_contact_turn"] == 2 == state["civs"]["saltreach"]["first_contact_turn"]
    sliced = worldgen.generate(CONFIG, 1)
    if sliced["civs"]["verdance"]["met"]:  # neighbours in sight at setup
        assert sliced["civs"]["verdance"]["first_contact_turn"] == 0


def test_a_mock_slice_trades_talks_and_replays_to_the_same_world(tmp_path):
    out = tmp_path / "slice"
    state, summary = run.play(CONFIG, 1, 40, out=out, mode="mock", llm_civs=list(run.SLICE_PAIR), bot="trader")
    assert summary["verdance"]["cost"]["first_contact"] == 0
    assert any(e["kind"] == "message" for e in state["events"]) and state["offers"]
    replayed, _ = run.play(CONFIG, 1, 40, mode="replay", llm_civs=list(run.SLICE_PAIR), bot="trader",
                           outputs=out / "outputs.jsonl")
    assert state_hash(replayed) == state_hash(state)
    assert llm.load_outputs(out / "outputs.jsonl")
