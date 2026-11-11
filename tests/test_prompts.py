"""The prompt-leak check and the Phase 2 check (PLAN sections 14 and 15).

One recorded 200-tick game with every civ played by the mock ruler through the text path. Every
system prompt and every message a ruler would have read is rendered and searched: before a civ
has met another, nothing it reads may name that civ or its goods, or hint at how many civs there
are or how big the map is. The same game checks the Phase 2 "done when".
"""

import json
import re

import pytest

from fogline import llm, prompts, run, schema
from fogline.config import Config

CONFIG = Config()
TICKS = 200

# Words that would tell a ruler it isn't alone. The size numbers are checked in the system prompt
# only: in a report they would match ordinary stock counts.
HINTS = re.compile(r"\bcivs?\b|civili[sz]ation|\brivals?\b|\boutsiders?\b|foreign|\bstrangers?\b|"
                   r"\bmet\b|other (?:peoples?|nations?|realms?|rulers?)|\bneighbours?\b|\benem(?:y|ies)\b|"
                   r"\binvad\w*|\bby force\b|\bstrike first\b", re.IGNORECASE)
SIZE = re.compile(r"\bmap\b|\b76\b|\b64\b", re.IGNORECASE)


def _hints(text, pattern=HINTS):
    return [m.group(0) for m in pattern.finditer(text)]


def _words_of(civ_id):
    spec = CONFIG.civ(civ_id)
    return {civ_id, spec.name.lower(), spec.luxury.lower()}


def _named(text, civ_ids):
    lowered = text.lower()
    return sorted(w for c in civ_ids for w in _words_of(c) if re.search(rf"\b{re.escape(w)}\b", lowered))


@pytest.fixture(scope="module")
def game(tmp_path_factory):
    out = tmp_path_factory.mktemp("phase2") / "mock"
    state, summary = run.play(CONFIG, 1, TICKS, out=out, mode="mock")
    records = [json.loads(line) for line in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    return state, summary, records, llm.load_outputs(out / "outputs.jsonl")


@pytest.mark.parametrize("civ_id", [c.civ_id for c in CONFIG.civs if prompts.has_culture(c.civ_id)])
def test_a_system_prompt_names_no_one_else_and_hides_the_world(civ_id):
    text = prompts.system_prompt(CONFIG, civ_id)
    others = [c.civ_id for c in CONFIG.civs if c.civ_id != civ_id]
    assert _named(text, others) == []
    assert _hints(text) == [] and _hints(text, SIZE) == []
    assert "{{" not in text and '"next_wake"' in text
    assert len(text) < 30_000  # it goes on the command line, which Windows caps near 32,000


def test_nothing_a_ruler_reads_names_a_civ_it_has_not_met(game):
    _, _, records, _ = game
    checked = 0
    for record in records:
        seen = record["observation"]
        if seen is None:
            continue
        message = prompts.user_message(seen if record["step"] == "decide" else {"step": "reflect", "observation": seen})
        met_names = {m["name"] for m in seen.get("met", [])}
        unmet = [c.civ_id for c in CONFIG.civs if c.civ_id != record["civ"] and c.name not in met_names]
        assert _named(message, unmet) == [], (record["tick"], record["civ"])
        if not met_names:
            assert _hints(message) == [], (record["tick"], record["civ"], _hints(message))
        checked += 1
    assert checked > 500


def test_mock_rulers_play_two_hundred_ticks_through_the_text_path(game):
    state, summary, records, rows = game
    assert state["tick"] == TICKS
    assert rows and {r["status"] for r in rows} == {llm.OK}
    for row in rows:
        if row["step"] == "decide":
            reply, refused = schema.validate_reply(row["raw"])
        else:
            reply, refused = schema.validate_reflection(row["raw"])
        assert reply is not None and refused == [], (row["tick"], row["civ"])
    assert all("calls" in summary[c] for c in state["civs"])
    assert any(state["civs"][c]["memory"]["journal"] for c in state["civs"])  # set_note was used


def test_every_rejected_order_comes_back_in_the_rulers_next_report(game):
    _, _, records, _ = game
    rejected = 0
    for civ_id in sorted({r["civ"] for r in records}):
        turns = [r for r in records if r["civ"] == civ_id and r["step"] == "decide"]
        for this, after in zip(turns, turns[1:]):
            if not this["rejections"]:
                continue
            following = next((r for r in turns if r["tick"] > this["tick"] and r["observation"]), None)
            if following is None:
                continue
            for rejection in this["rejections"]:
                assert rejection in following["observation"]["rejections"], (civ_id, this["tick"], rejection)
                rejected += 1
    assert rejected >= 20, "the mock ruler's bad orders should give plenty of rejections to check"
