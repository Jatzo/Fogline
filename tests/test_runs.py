"""Whole runs: the 1,000-tick smoke run, determinism across processes, RNG isolation and resume.

These are the Phase 1 checks that hold whatever the tuning numbers are (plan fixes 1 to 3).
"""

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fogline import actions, bots, engine, ledger, rng, run, snapshot, worldgen
from fogline.config import Config
from fogline.state import state_hash
from test_engine import _assert_conserved

ROOT = Path(__file__).resolve().parents[1]


def _python(code: str, hash_seed: str) -> str:
    """Run code in a fresh interpreter and return what it prints."""
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT,
                          check=True, timeout=300)
    return done.stdout.strip()


def test_a_thousand_ticks_with_events_on_run_and_stay_conserved():
    state, summary = run.play(Config(), 1, 1000)
    assert state["tick"] == 1000
    _assert_conserved(state)
    assert set(summary) == set(state["civs"])


def test_the_same_seed_gives_the_same_hash_in_two_processes():
    code = ("from fogline import run; from fogline.config import Config; from fogline.state import state_hash; "
            "s, _ = run.play(Config(), 1, 120); print(state_hash(s))")
    first = _python(code, "0")
    second = _python(code, "4242")
    assert first == second and len(first) == 64


def _civ_view(state: dict, civ_id: str) -> dict:
    """Everything that is one civ's own, leaving out the event cursor (an index into the shared
    event list, which moves when another civ records more)."""
    civ = {key: value for key, value in state["civs"][civ_id].items() if key != "turn"}
    civ["turn"] = {key: value for key, value in state["civs"][civ_id]["turn"].items() if key != "cursor"}
    return {
        "civ": civ,
        "settlements": {k: v for k, v in state["settlements"].items() if v["civ"] == civ_id},
        "units": {k: v for k, v in state["units"].items() if v["civ"] == civ_id},
        "events": [e for e in state["events"] if e["civ"] == civ_id],
        "territory": sorted(t for t, sid in state["territory"].items() if state["settlements"][sid]["civ"] == civ_id),
    }


def test_changing_one_civs_ruler_leaves_every_other_civ_untouched(monkeypatch):
    config = Config()
    draws: list[tuple] = []
    real_stream = rng.stream

    def recording_stream(seed, system, tick, civ, purpose):
        draws.append((system, tick, civ, purpose))
        return real_stream(seed, system, tick, civ, purpose)

    monkeypatch.setattr(rng, "stream", recording_stream)

    def play(ironhold_ruler):
        draws.clear()
        state = worldgen.generate(config, 3)
        deciders = run.deciders_for(config, state)
        deciders["ironhold"] = ironhold_ruler
        engine.run(config, state, 100, deciders=deciders)
        return state, list(draws)

    base, base_draws = play(run.BOTS["builder"](config, "ironhold"))
    other, other_draws = play(bots.idle)
    assert state_hash(_civ_view(base, "ironhold")) != state_hash(_civ_view(other, "ironhold"))
    for civ_id in sorted(base["civs"]):
        if civ_id == "ironhold":
            continue
        assert state_hash(_civ_view(base, civ_id)) == state_hash(_civ_view(other, civ_id)), civ_id
        assert [d for d in base_draws if d[2] == civ_id] == [d for d in other_draws if d[2] == civ_id], civ_id
    # The world stream (which civ an event hits) never depends on what any civ did.
    assert [d for d in base_draws if d[2] == rng.WORLD] == [d for d in other_draws if d[2] == rng.WORLD]


def test_a_run_resumed_in_a_fresh_process_matches_an_unbroken_one(tmp_path):
    # Events every tick, so a drought is under way when the snapshot is taken.
    config = dataclasses.replace(Config(), world_event_chance=1000)
    state = worldgen.generate(config, 1)
    deciders = run.deciders_for(config, state)
    while not (state["tick"] >= 40 and state["tick"] % 4 == 2 and any(
            m["rate"] == config.drought_rate and m["until"] > state["tick"]
            for civ in state["civs"].values() for m in civ["modifiers"])):
        engine.tick(config, state, deciders=deciders)
        assert state["tick"] < 400, "no drought on seed 1 with events every tick"
    # Queue a two-tick workshop through the action path, so a build is half done at the winter
    # snapshot. Its cost is topped up through the ledger, so conservation still holds.
    civ_id = next(c for c in sorted(state["civs"]) if engine.civ_pop(state, c) > 0)
    stocks = state["civs"][civ_id]["stocks"]
    for resource in ("timber", "stone"):
        ledger.apply(stocks, state["ledger"], None, civ_id, resource, 100, ledger.Rule.PRODUCTION, state["tick"])
    assert actions.build(config, state, civ_id, f"{civ_id}-0", "workshop") is None
    engine.tick(config, state, deciders=deciders)
    assert state["tick"] % 4 == 3
    assert any(e["started"] for civ in state["civs"].values() for e in civ["build_queue"])

    path = tmp_path / "snap.json.gz"
    snapshot.save(state, path)
    stop = state["tick"] + 40
    engine.run(config, state, stop - state["tick"], deciders=deciders)

    code = (f"import dataclasses; from pathlib import Path; from fogline import bots, engine, snapshot; "
            f"from fogline.config import Config; from fogline.state import state_hash; "
            f"c = dataclasses.replace(Config(), world_event_chance=1000); s = snapshot.load(Path(r'{path}')); "
            f"from fogline import run; engine.run(c, s, {stop} - s['tick'], deciders=run.deciders_for(c, s)); "
            f"print(state_hash(s))")
    assert _python(code, "777") == state_hash(state)


def test_a_snapshot_round_trips_to_the_same_hash(tmp_path):
    state = worldgen.generate(Config(), 2)
    path = tmp_path / "s.json.gz"
    snapshot.save(state, path)
    assert state_hash(snapshot.load(path)) == state_hash(state)
    first = path.read_bytes()
    snapshot.save(state, path)
    assert path.read_bytes() == first  # same state, same bytes
    assert str(tmp_path).encode() not in first and b"s.json" not in first  # no local path in the header


# The state hash of seed 1 after 200 ticks with builder bots and events on. Any change to the
# rules, the numbers or the bots changes it; the commit that does so says why.
GOLDEN_SEED_1_TICK_200 = "bbe4705aa9a3a86d13d8fc5298ad82614d853fbd85636736dbec06f6f4eb9413"


def test_seed_1_at_tick_200_matches_the_golden_hash():
    state, _ = run.play(Config(), 1, 200)
    assert state_hash(state) == GOLDEN_SEED_1_TICK_200


@pytest.fixture(scope="module")
def quiet_seed_1():
    """Seed 1 to tick 110 with events off: the default for tuning tests (plan fix 9)."""
    return run.play(dataclasses.replace(Config(), events_enabled=False), 1, 110)[1]


RUN_OUT_WINDOW = range(55, 86)  # rules 4.7 says tick 60 to 80; the tuning tests allow 5 ticks either side
CRITICAL = [("ironhold", "food"), ("verdance", "metal"), ("saltreach", "timber"), ("dunerunners", "food"),
            ("dunerunners", "timber"),
            ("frostmark", "stone")]


@pytest.mark.parametrize("civ_id, resource", CRITICAL)
def test_a_civ_that_never_trades_runs_out_of_its_critical_stock_on_schedule(quiet_seed_1, civ_id, resource):
    assert quiet_seed_1[civ_id]["run_out"][resource] in RUN_OUT_WINDOW, quiet_seed_1[civ_id]["run_out"]


@pytest.mark.parametrize("civ_id", ["dunerunners", "frostmark", "ironhold", "saltreach", "verdance"])
def test_a_civ_that_never_trades_has_declined_by_tick_100(quiet_seed_1, civ_id):
    row = quiet_seed_1[civ_id]
    pop_down = row["pop_at_100"] * 100 <= row["peak_pop"] * 85
    food_down = row["food_output_at_100"] * 100 <= row["peak_food_output"] * 85
    assert pop_down or food_down, row
