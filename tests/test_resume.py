"""Resuming a stopped run (Phase 4: "resumed sessions count"). A mock run stands in for a live
one: both go through the same recorder and the same text path, and the mock ruler keeps no state
of its own, so a resumed mock run must reach exactly the world an unbroken one does."""

import json
import shutil

import pytest

from fogline import llm, run
from fogline.config import Config
from fogline.state import state_hash

TICKS = 24
CIVS = ["saltreach", "verdance"]


@pytest.fixture(scope="module")
def whole(tmp_path_factory):
    out = tmp_path_factory.mktemp("resume") / "whole"
    state, _ = run.play(Config(), 1, TICKS, out=out, mode="mock", llm_civs=CIVS)
    return out, state_hash(state), llm.load_outputs(out / "outputs.jsonl")


def _stopped_copy(whole_dir, tmp_path, keep_through, failed_ticks=()):
    """The whole run cut short after keep_through, as if it stopped there, with optional ticks
    at the end where every call failed."""
    out = tmp_path / "stopped"
    shutil.copytree(whole_dir, out)
    rows = [r for r in llm.load_outputs(out / "outputs.jsonl") if r["tick"] <= keep_through]
    for tick in failed_ticks:
        rows += [{"tick": tick, "civ": civ, "step": "decide", "status": llm.ERROR, "raw": "usage limit",
                  "obs_hash": "", "usage": None} for civ in CIVS]
    (out / "outputs.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    return out


def test_a_resumed_run_reaches_the_world_an_unbroken_run_does(whole, tmp_path):
    whole_dir, final_hash, whole_rows = whole
    out = _stopped_copy(whole_dir, tmp_path, keep_through=13)
    state, summary = run.resume(out)
    assert state_hash(state) == final_hash
    key = lambda r: (r["tick"], r["civ"], r["step"])  # noqa: E731
    assert sorted((key(r), r["raw"]) for r in llm.load_outputs(out / "outputs.jsonl")) == \
        sorted((key(r), r["raw"]) for r in whole_rows)
    manifest = json.loads((out / "manifest.json").read_text(encoding="ascii"))
    assert len(manifest["resumed_at"]) == 1 and manifest["resumed_at"][0] <= 13
    assert (out / f"snap-{TICKS:05d}.json.gz").exists() and "verdance" in summary


def test_ticks_where_every_call_failed_are_played_again_not_replayed(whole, tmp_path):
    whole_dir, final_hash, _ = whole
    out = _stopped_copy(whole_dir, tmp_path, keep_through=13, failed_ticks=(14, 15))
    stopped = llm.load_outputs(out / "outputs.jsonl")
    assert run.resume_point(stopped) == 14
    state, summary = run.resume(out)
    assert state_hash(state) == final_hash
    assert llm.load_outputs(out / "before-resume-1" / "outputs.jsonl") == stopped  # every call kept
    dropped = sum(summary[c]["dropped_on_resume"]["calls"] for c in summary if "dropped_on_resume" in summary[c])
    assert dropped == sum(1 for r in stopped if r["tick"] >= 14)


def test_a_resume_that_doesnt_reach_the_saved_world_stops_and_puts_everything_back(whole, tmp_path):
    whole_dir, _, _ = whole
    out = _stopped_copy(whole_dir, tmp_path, keep_through=13)
    shutil.copy(out / "snap-00004.json.gz", out / "snap-00012.json.gz")  # the snapshot no longer matches tick 12
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(llm.ReplayError, match="tick 12"):
        run.resume(out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before  # so a second try checks the same world
    with pytest.raises(llm.ReplayError, match="tick 12"):
        run.resume(out)


def test_a_last_line_cut_off_mid_write_doesnt_block_a_resume(whole, tmp_path):
    whole_dir, final_hash, _ = whole
    out = _stopped_copy(whole_dir, tmp_path, keep_through=13)
    with open(out / "outputs.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"tick": 14, "civ": "verd')
    state, _ = run.resume(out)
    assert state_hash(state) == final_hash


def test_the_resume_point_drops_the_last_tick_and_any_failed_ticks_before_it():
    def rows(*statuses_by_tick):
        return [{"tick": t, "status": s} for t, statuses in statuses_by_tick for s in statuses]
    assert run.resume_point([]) == 0
    assert run.resume_point(rows((0, ["ok"]), (3, ["ok"]), (5, ["ok"]))) == 5
    assert run.resume_point(rows((0, ["ok"]), (3, ["ok", "error"]), (5, ["error"]), (6, ["timeout"]))) == 5
    assert run.resume_point(rows((0, ["error"]), (1, ["error"]))) == 0


def test_only_a_mock_or_live_run_can_be_resumed(tmp_path):
    out = tmp_path / "bots"
    run.play(Config(), 1, 4, out=out)
    with pytest.raises(ValueError, match="mock or live"):
        run.resume(out)
