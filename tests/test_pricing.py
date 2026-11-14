"""Ruler calls priced from list prices (fogline/pricing.py), and the model roster (fogline/run.py).

`claude -p` priced claude-haiku-5-5 as Opus 5.5 (docs/debug-log.md); these tests hold the fix."""

import json
from pathlib import Path

import pytest

from fogline import llm, pricing, run

RUNS = Path(__file__).resolve().parents[1] / "runs"


def test_a_haiku_call_is_priced_from_the_table_not_from_what_claude_p_reported():
    # The tiny call of 2026-11-14: claude -p reported $0.00954, which is Opus 5.5's price.
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 1094, "cache_write_1h": 1094,
             "cache_read_input_tokens": 0, "output_tokens": 39, "total_cost_usd": 0.00954}
    assert pricing.cost("claude-opus-5-5", usage) == pytest.approx(0.00954, abs=1e-5)  # what it really charged for
    assert pricing.cost("claude-haiku-5-5", usage) == pytest.approx(0.00024, abs=1e-5)


def test_cache_writes_are_priced_by_their_lifetime_and_long_haiku_prompts_cost_more():
    short = {"cache_creation_input_tokens": 1_000_000, "cache_write_5m": 1_000_000}
    assert pricing.cost("claude-sonnet-5-5", short) == pytest.approx(2.50)
    assert pricing.cost("claude-sonnet-5-5", {"cache_creation_input_tokens": 1_000_000}, "5m") == pytest.approx(2.50)
    assert pricing.cost("claude-sonnet-5-5", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(4.00)
    assert pricing.cost("claude-haiku-5-5", {"input_tokens": 200_000}) == pytest.approx(0.10)   # the long rate, $0.50
    assert pricing.cost("claude-haiku-5-5", {"input_tokens": 100_000}) == pytest.approx(0.01)


def test_every_model_in_the_roster_has_a_price_and_an_unknown_one_is_refused():
    assert set(run.ROSTER) <= set(pricing.RATES) and pricing.PRICES_READ_ON
    with pytest.raises(pricing.UnknownModel):
        pricing.cost("claude-imaginary-1", {"output_tokens": 1})
    with pytest.raises(pricing.UnknownModel):
        run.roster(("claude-imaginary-1",), ["verdance"], 1)


@pytest.mark.skipif(not (RUNS / "live-slice-s1" / "outputs.jsonl").is_file(), reason="needs the gitignored M19 run")
def test_the_m19_costs_claude_p_reported_are_opus_prices_to_the_cent():
    rows = [json.loads(line) for line in (RUNS / "live-slice-s1" / "outputs.jsonl").open(encoding="utf-8") if line.strip()]
    reported = sum(r["usage"]["total_cost_usd"] for r in rows)
    assert sum(pricing.cost("claude-opus-5-5", r["usage"]) for r in rows) == pytest.approx(reported, abs=0.01)
    assert sum(pricing.row_cost(r) for r in rows) < reported / 30


def test_the_roster_rotates_by_seed_so_every_civ_plays_every_model():
    civs = ["dunerunners", "frostmark", "ironhold", "saltreach", "verdance"]
    seen = {civ: set() for civ in civs}
    for seed in (1, 2, 3):
        ruled = run.roster(run.ROSTER, civs, seed)
        assert sorted(ruled.values()).count("claude-haiku-5-5") in (1, 2)
        for civ, model in ruled.items():
            seen[civ].add(model)
    assert all(models == set(run.ROSTER) for models in seen.values())
    assert run.roster(("claude-haiku-5-5",), civs, 7) == {civ: "claude-haiku-5-5" for civ in civs}


def test_each_civ_is_called_with_its_own_model(monkeypatch):
    sent = []

    def fake_run(argv, **kwargs):
        sent.append(argv[argv.index("--model") + 1])
        return llm.subprocess.CompletedProcess(argv, 0, json.dumps({"is_error": False, "result": "{}"}), "")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    adapter = llm.LiveAdapter(lambda civ, met: "rules", {"verdance": "claude-opus-5-5"})
    recorder = llm.Recorder(adapter)
    recorder.call((0, "verdance", "decide"), {"tick": 0})
    recorder.call((0, "ironhold", "decide"), {"tick": 0})
    assert sent == ["claude-opus-5-5", "claude-haiku-5-5"]
    assert [r["model"] for r in recorder.rows] == sent


def test_a_manifest_from_before_the_roster_reads_as_one_model_for_every_ruler():
    old = {"llm": "live", "llm_civs": ["saltreach", "verdance"], "model": "claude-haiku-5-5"}
    assert run.manifest_models(old) == {"saltreach": "claude-haiku-5-5", "verdance": "claude-haiku-5-5"}
    assert run.manifest_models({"llm": "mock", "llm_civs": ["verdance"]}) == {}
    assert run.manifest_models({"llm": "live", "llm_civs": ["x"], "models": {"x": "claude-opus-5-5"}}) == {"x": "claude-opus-5-5"}
