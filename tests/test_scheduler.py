"""Calling rulers together (PLAN section 10) and running a world through the LLM modes."""

import dataclasses
import json
import sys
import threading
import time

import pytest

from fogline import engine, llm, run, scheduler, worldgen
from fogline.config import Config
from fogline.state import state_hash

CONFIG = Config()


def test_replies_come_back_in_civ_order_whatever_order_they_finish():
    finished = []

    def call(civ, delay):
        def go():
            time.sleep(delay)
            finished.append(civ)
            return civ.upper()
        return go

    calls = {"a": call("a", 0.15), "b": call("b", 0.10), "c": call("c", 0.05), "d": call("d", 0.0)}
    assert list(scheduler.call_all(calls, cap=4).items()) == [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")]
    assert finished == ["d", "c", "b", "a"]


def test_no_more_than_the_cap_run_at_once():
    lock, live, peak = threading.Lock(), [0], [0]

    def call():
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1

    scheduler.call_all({f"c{n}": call for n in range(8)}, cap=3)
    assert peak[0] == 3


class _ReverseFinish:
    """A mock adapter that answers the civs in reverse id order: the last civ first."""

    def __init__(self, inner, civs):
        self.inner, self.delay = inner, {civ: 0.01 * n for n, civ in enumerate(sorted(civs))}

    def call(self, key, observation):
        time.sleep(self.delay[key[1]])
        return self.inner.call(key, observation)


def test_a_world_called_in_parallel_matches_one_called_in_turn():
    def play(cap, slow):
        config = dataclasses.replace(CONFIG, max_concurrent_calls=cap)
        state = worldgen.generate(config, 1)
        mock = llm.MockAdapter(run.deciders_for(config, state))
        adapter = _ReverseFinish(mock, state["civs"]) if slow else mock
        deciders = {civ: llm.make_ruler(adapter, civ) for civ in state["civs"]}
        engine.run(config, state, 12, deciders=deciders)
        return state_hash({k: v for k, v in state.items() if k != "config_hash"})

    assert play(cap=5, slow=True) == play(cap=1, slow=False)


def test_a_mock_run_writes_outputs_that_replay_from_the_command_line(tmp_path, monkeypatch):
    recorded = tmp_path / "mock"
    state, summary = run.play(CONFIG, 1, 24, out=recorded, mode="mock", llm_civs=["verdance", "ironhold"])
    manifest = json.loads((recorded / "manifest.json").read_text(encoding="ascii"))
    assert manifest["llm"] == "mock" and manifest["llm_civs"] == ["ironhold", "verdance"]
    rows = llm.load_outputs(recorded / "outputs.jsonl")
    assert {row["civ"] for row in rows} == {"ironhold", "verdance"}
    assert summary["verdance"]["calls"] == {"ok": sum(1 for r in rows if r["civ"] == "verdance")}
    assert "calls" not in summary["frostmark"]

    replayed, _ = run.play(CONFIG, 1, 24, mode="replay", llm_civs=["verdance", "ironhold"],
                           outputs=recorded / "outputs.jsonl")
    assert state_hash(replayed) == state_hash(state)

    monkeypatch.setattr(sys, "argv", ["fogline.run", "--ticks", "24", "--llm", "replay", "--llm-civs",
                                      "verdance,ironhold", "--outputs", str(recorded / "outputs.jsonl")])
    run.main()


@pytest.mark.parametrize("argv, message", [
    (["--llm", "replay"], "needs --outputs"),
    (["--llm", "live"], "needs --out"),
    (["--llm", "live", "--llm-civs", "ironhold", "--out", "{tmp}"], "no culture prompt for ironhold"),
    (["--llm", "mock", "--llm-civs", "atlantis"], "no such civ"),
])
def test_the_runner_refuses_an_incomplete_llm_setup(monkeypatch, capsys, tmp_path, argv, message):
    # Every civ has a culture now, so a missing one is faked; the refusal must come before any call.
    monkeypatch.setattr(run.prompts, "has_culture", lambda civ_id: civ_id != "ironhold")
    argv = [str(tmp_path / "run") if a == "{tmp}" else a for a in argv]
    monkeypatch.setattr(sys, "argv", ["fogline.run", "--ticks", "1", *argv])
    with pytest.raises(SystemExit) as stopped:
        run.main()
    assert stopped.value.code == 2 and message in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_a_test_that_reaches_a_live_call_fails_instead_of_calling(tmp_path):
    # Regression (docs/debug-log.md): once Ironhold had a culture, the test above ran a real call.
    adapter = llm.LiveAdapter(lambda civ, met: "prompt")
    with pytest.raises(pytest.fail.Exception, match="live call"):
        adapter.call((0, "verdance", "decide"), {"tick": 0})
