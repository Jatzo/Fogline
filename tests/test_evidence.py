"""The model evidence pack (fogline/evidence.py): its tables add up to the run's own records."""

import json
import re
from collections import Counter

import pytest

from fogline import evidence, phase4, run, snapshot
from fogline.config import Config

LIVE = ["saltreach", "verdance"]


@pytest.fixture(scope="module")
def mock_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("evidence") / "mock"
    run.play(Config(), 1, 42, out=out, mode="mock", llm_civs=LIVE)
    return out


def _rows(text: str, heading: str) -> list[list[str]]:
    """The data rows of the first table after a heading line."""
    lines = text[text.index(heading):].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|---"))
    rows = []
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_the_action_counts_are_the_turn_logs_applied_actions(mock_run):
    text = evidence.pack([evidence.load(mock_run)])
    records = [json.loads(line) for line in (mock_run / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    for row in _rows(text, "| Civ | Applied actions by kind"):
        civ = row[0].split()[0].lower()
        expected = sum((phase4.applied_actions(r) for r in records if r["civ"] == civ), Counter())
        shown = Counter({k: int(n) for k, n in (part.rsplit(" ", 1) for part in row[1].split(", "))})
        assert shown == expected


def test_refusals_per_window_add_up_to_the_stored_rejections(mock_run):
    text = evidence.pack([evidence.load(mock_run)])
    records = [json.loads(line) for line in (mock_run / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = _rows(text, "### Learning: refused actions")
    assert [row[0].split()[0].lower() for row in rows] == LIVE
    for row in rows:
        civ = row[0].split()[0].lower()
        cells = [re.match(r"(\d+)/(\d+)", cell).groups() for cell in row[1:-1]]
        turns = [r for r in records if r["civ"] == civ and r["step"] == "decide"]
        assert sum(int(a) for a, _ in cells) == sum(len(evidence.refused(r)) for r in turns)
        assert sum(int(b) for _, b in cells) == sum(evidence.proposed(r) for r in turns)


def test_progress_rows_read_the_snapshot_they_name(mock_run):
    loaded = evidence.load(mock_run)
    text = evidence.pack([loaded])
    row = _rows(text, "**Verdance (Mock)**")[1]   # the second row: the snapshot at or before tick 42
    state = snapshot.load(mock_run / f"snap-{int(row[0]):05d}.json.gz")
    figures = evidence.civ_figures(state, "verdance")
    assert row[1:] == [str(figures["pop"]), str(figures["techs"]), str(figures["stability"]),
                       figures["settlements"], figures["stocks"]]


def test_the_pooled_model_table_appears_only_for_more_than_one_run(mock_run):
    one = evidence.load(mock_run)
    assert "pooled per model" not in evidence.pack([one])
    rows = _rows(evidence.pack([one, one]), "## Across runs, pooled per model")
    assert rows[0][:2] == ["Mock", "4"]   # two civs from each of the two runs


def test_windows_cover_every_tick_once_with_the_last_reaching_the_end():
    assert evidence.stretches(400)[-1] == (350, 401)
    assert evidence.stretches(42) == [(0, 43)]
    assert evidence.stretches(120) == [(0, 50), (50, 100), (100, 121)]


def test_excerpts_are_a_fixed_cut_and_cannot_break_out_of_their_code_block():
    text = "Tick 96, spring. " + "word " * 80 + "```"
    cut = evidence.opening(text)
    assert cut.startswith("Tick 96, spring. word") and cut.endswith(" ...") and len(cut) <= evidence.EXCERPT_CHARS + 4
    assert "`" not in evidence.opening("a ``` b")


def test_a_share_needs_enough_proposals_to_be_a_percentage():
    assert evidence.share(3, 9) == "3/9"
    assert evidence.share(3, 10) == "3/10 (30%)"


def test_a_run_still_playing_is_cut_at_its_last_snapshot(mock_run, tmp_path):
    # Logs run every tick and snapshots every few, so a pack read mid-run would count calls past the
    # ticks its other tables cover.
    import shutil
    playing = tmp_path / "playing"
    shutil.copytree(mock_run, playing)
    (playing / "snap-00042.json.gz").unlink()   # as if the run were at tick 42 with tick 40 its last snapshot
    loaded = evidence.load(playing)
    assert loaded.final["tick"] == 40
    assert loaded.records and max(r["tick"] for r in loaded.records) <= 40
    assert all(r["tick"] <= 40 for r in loaded.outputs)
