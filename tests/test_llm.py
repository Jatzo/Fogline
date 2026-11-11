"""The adapter, stored outputs and replay (PLAN sections 10, 11 and 14). No live calls."""

import json
import subprocess

import pytest

from fogline import bots, engine, llm, run, worldgen
from fogline.config import Config
from fogline.state import state_hash
from test_engine import _assert_conserved
from test_runs import _civ_view

CONFIG = Config()


def _rulers(state, adapter_for):
    return {civ: llm.make_ruler(adapter_for(civ), civ) for civ in sorted(state["civs"])}


def _record(seed, ticks, inner=None, path=None):
    state = worldgen.generate(CONFIG, seed)
    recorder = llm.Recorder(inner or llm.MockAdapter(run.deciders_for(CONFIG, state)), path)
    engine.run(CONFIG, state, ticks, deciders=_rulers(state, lambda civ: recorder))
    return state, recorder.rows


def _replay(seed, ticks, rows, adapter_for=None):
    state = worldgen.generate(CONFIG, seed)
    replay = llm.ReplayAdapter(rows)
    engine.run(CONFIG, state, ticks, deciders=_rulers(state, adapter_for or (lambda civ: replay)))
    return state


def test_a_recorded_run_replays_to_the_same_hash(tmp_path):
    path = tmp_path / "outputs.jsonl"
    recorded, rows = _record(1, 60, path=path)
    assert rows and all(row["status"] == "ok" for row in rows)
    assert llm.load_outputs(path) == rows
    assert any(json.loads(row["raw"])["actions"] for row in rows)  # the mock really did act
    replayed = _replay(1, 60, llm.load_outputs(path))
    assert state_hash(replayed) == state_hash(recorded)
    _assert_conserved(replayed)


class _Flaky:
    """Times out for one civ on one tick, and errors for another, around a working adapter."""

    def __init__(self, inner):
        self.inner = inner

    def call(self, key, observation):
        tick, civ, _ = key
        if (tick, civ) == (6, "verdance"):
            return llm.Outcome(llm.TIMEOUT, "no reply in 90 s")
        if (tick, civ) == (6, "ironhold"):
            return llm.Outcome(llm.ERROR, "exit 1: rate limited")
        return self.inner.call(key, observation)


def test_a_stored_timeout_replays_as_an_empty_turn_without_timing_anything():
    state = worldgen.generate(CONFIG, 1)
    recorder = llm.Recorder(_Flaky(llm.MockAdapter(run.deciders_for(CONFIG, state))))
    records = engine.run(CONFIG, state, 12, deciders=_rulers(state, lambda civ: recorder))
    stored = {(r["tick"], r["civ"]): r["status"] for r in recorder.rows}
    assert stored[(6, "verdance")] == llm.TIMEOUT and stored[(6, "ironhold")] == llm.ERROR
    empty = [r for r in records if r.tick == 6 and r.civ in ("verdance", "ironhold")]
    assert empty and all(r.reply is None and not r.rejections for r in empty)
    assert state_hash(_replay(1, 12, recorder.rows)) == state_hash(state)


def test_replay_refuses_a_changed_observation_or_a_missing_output():
    _, rows = _record(1, 10)
    state = worldgen.generate(CONFIG, 1)
    state["civs"]["verdance"]["stability"] += 1  # the world the outputs answered is not this one
    replay = llm.ReplayAdapter(rows)
    with pytest.raises(llm.ReplayError, match="differs"):
        engine.run(CONFIG, state, 10, deciders=_rulers(state, lambda civ: replay))
    with pytest.raises(llm.ReplayError, match="no stored output"):
        _replay(1, 10, [r for r in rows if (r["tick"], r["civ"]) != (0, "frostmark")])


def test_unparseable_text_is_refused_and_the_reason_comes_back(tmp_path):
    class Garbled:
        def call(self, key, observation):
            return llm.Outcome(llm.OK, "Sure! Here is my plan: build more farms.")

    state = worldgen.generate(CONFIG, 1)
    seen = []
    ruler = llm.make_ruler(Garbled(), "verdance")

    def watching(observation, scratch):
        seen.append(observation)
        return ruler(observation, scratch)

    engine.run(CONFIG, state, 2, deciders={"verdance": watching})
    assert seen[1]["rejections"] == [{"index": -1, "kind": "not_json", "reason": "unparseable_reply"}]
    assert state["civs"]["verdance"]["turn"]["invalid_streak"] == 2


def test_changing_one_civs_outputs_leaves_every_other_civ_untouched():
    # Seed 3 to tick 100, as in the M6 isolation test: no contact, so nothing one civ does can
    # reach another's observation. Ironhold answers differently; everyone else replays, and the
    # replay would fail loudly if any of their observations moved.
    recorded, rows = _record(3, 100)
    idle = llm.MockAdapter({"ironhold": bots.idle})
    replay = llm.ReplayAdapter(rows)
    changed = _replay(3, 100, rows, lambda civ: idle if civ == "ironhold" else replay)
    assert state_hash(_civ_view(changed, "ironhold")) != state_hash(_civ_view(recorded, "ironhold"))
    for civ_id in sorted(recorded["civs"]):
        if civ_id != "ironhold":
            assert state_hash(_civ_view(changed, civ_id)) == state_hash(_civ_view(recorded, civ_id)), civ_id


def test_the_live_adapter_reports_a_failed_command_as_an_error_not_a_crash():
    adapter = llm.LiveAdapter("system", command=("fogline-no-such-command",))
    outcome = adapter.call((0, "verdance", "decide"), {"tick": 0})
    assert outcome.status == llm.ERROR and "could not start" in outcome.raw


def test_the_live_adapter_runs_in_safe_mode_and_reads_the_result(monkeypatch):
    # Without --safe-mode the operator's own instructions and hook output reach the ruler (ADR 0007).
    sent = {}

    def fake_run(argv, **kwargs):
        sent["argv"], sent["input"] = argv, kwargs["input"]
        envelope = {"type": "result", "is_error": False, "result": '{"actions": []}'}
        return subprocess.CompletedProcess(argv, 0, json.dumps(envelope), "")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    outcome = llm.LiveAdapter("rules of play").call((0, "verdance", "decide"), {"tick": 0})
    assert outcome == llm.Outcome(llm.OK, '{"actions": []}')
    argv = sent["argv"]
    assert "--safe-mode" in argv and argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == "rules of play"
    assert sent["input"] == '{"tick":0}'
