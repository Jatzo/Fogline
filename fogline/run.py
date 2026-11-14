"""Headless runner: python -m fogline.run --seed 1 --ticks 1000

Plays a seeded world with scripted rulers and prints, for each civ, when its critical stocks
ran out, when it finished the tech tree, how its towns grew, and what each town is like. With
--out it also writes a run folder: a manifest, a snapshot every year, the ledger log and the
turn records, all outside the hashed state.
"""

import argparse
import dataclasses
import json
from pathlib import Path

from fogline import bots, engine, llm, pricing, prompts, snapshot, techs, units, worldgen
from fogline.agents import mock_ruler
from fogline.config import Config
from fogline.state import state_hash

BOTS = {"builder": lambda config, civ_id: bots.make_builder(config, "food" in config.civ(civ_id).short_of),
        "spiral": lambda config, civ_id: bots.spiral_scout, "idle": lambda config, civ_id: bots.idle,
        "trader": lambda config, civ_id: bots.make_trader(config, civ_id)}


def deciders_for(config: Config, state: dict, bot: str = "builder") -> dict:
    """One scripted ruler per civ."""
    return {civ_id: BOTS[bot](config, civ_id) for civ_id in sorted(state["civs"])}


LLM_MODES = ("bots", "mock", "replay", "live")
# The models a live run's rulers are drawn from, rotated by seed (PLAN section 1, ADR 0012).
ROSTER = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")


def roster(models: tuple[str, ...], llm_civs: list[str], seed: int) -> dict[str, str]:
    """Which model rules each live civ: the i-th in sorted order gets models[(i + seed) % len].
    Over len(models) seeds every civ plays every model once, so a model's effect can be told
    apart from a culture's. Worked out once when a run starts and kept in its manifest."""
    for model in models:
        pricing.rates_for(model)   # an unpriced model is refused before any call
    return {civ: models[(i + seed) % len(models)] for i, civ in enumerate(sorted(llm_civs))}
SLICE_PAIR = ("verdance", "saltreach")  # Phase 3b (operator's choice, rules 21)
FAILED_TICKS_TO_STOP = {llm.ERROR: 3, llm.TIMEOUT: 5}  # ticks in a row where every live call failed


def cost_meter(rows: list[dict], state: dict, start_tick: int, end_tick: int,
               models: dict[str, str] | None = None) -> dict[str, dict]:
    """Per civ: calls, tokens and cost before and after its first contact, each also per 100 ticks
    of that stretch, with the call counts behind every figure (PLAN section 10, Phase 3b)."""
    meter = {}
    for civ_id in sorted({r["civ"] for r in rows}):
        met, seen = state["civs"][civ_id]["met"], state["civs"][civ_id].get("first_contact_turn")
        contact = end_tick if seen is None else min(seen, end_tick)
        spans = {"before_contact": (start_tick, contact), "after_contact": (contact, end_tick)}
        meter[civ_id] = {"first_contact": min(met.values()) if met else None, "first_contact_turn": seen}
        for name, (low, high) in spans.items():
            mine = [r for r in rows if r["civ"] == civ_id and low <= r["tick"] < high]
            spent = {"ticks": high - low, "calls": len(mine), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            for row in mine:
                usage = row.get("usage") or {}
                spent["input_tokens"] += usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)                     + usage.get("cache_read_input_tokens", 0)
                spent["output_tokens"] += usage.get("output_tokens", 0)
                spent["cost_usd"] += pricing.row_cost(row, (models or {}).get(civ_id, pricing.DEFAULT_MODEL))
            if spent["ticks"] > 0:
                spent["per_100_ticks"] = {"calls": round(spent["calls"] * 100 / spent["ticks"], 1),
                                          "cost_usd": round(spent["cost_usd"] * 100 / spent["ticks"], 4)}
            spent["cost_usd"] = round(spent["cost_usd"], 4)
            meter[civ_id][name] = spent
    return meter


class Failing:
    """Counts ticks in a row where every live call failed the same way. Read on the main thread
    after each tick, so thread order can't hide a failure."""

    def __init__(self) -> None:
        self.streak = {status: 0 for status in FAILED_TICKS_TO_STOP}

    def after(self, rows: list[dict]) -> None:
        if not rows:
            return
        statuses = {r["status"] for r in rows}
        for status, limit in FAILED_TICKS_TO_STOP.items():
            self.streak[status] = self.streak[status] + 1 if statuses == {status} else 0
            if self.streak[status] >= limit:
                raise llm.LiveFailure(f"every live call failed ({status}) for {limit} ticks in a row; "
                                      f"last: {rows[-1]['raw']}")


def rulers(config: Config, state: dict, bot: str, mode: str, llm_civs: list[str] | None,
           outputs: Path | None, out: Path | None,
           resumed: tuple[list[dict], int, int, str] | None = None,
           models: dict[str, str] | None = None) -> tuple[dict, llm.Recorder | None]:
    """The deciders for a run, and the recorder if outputs are being kept.

    bots: every civ is a scripted bot, called directly. mock: the chosen civs are mock rulers
    (fogline/agents/mock_ruler.py) speaking through the text adapter, as an LLM would. replay: the chosen civs answer from stored outputs. live: the
    chosen civs call `claude -p` with their prompts (fogline/prompts.py). Civs not chosen stay scripted bots.
    """
    deciders = deciders_for(config, state, bot)
    if mode == "bots":
        return deciders, None
    chosen = sorted(llm_civs or state["civs"])
    unknown = set(chosen) - set(state["civs"])
    if unknown:
        raise ValueError(f"no such civ: {', '.join(sorted(unknown))}")
    recorder = None
    if mode == "replay":
        if outputs is None:
            raise ValueError("--llm replay needs --outputs, the outputs.jsonl of the run to replay")
        adapter: llm.Adapter = llm.ReplayAdapter(llm.load_outputs(outputs))
    else:
        if mode == "live":
            if out is None:
                raise ValueError("--llm live needs --out, so every call is kept")
            missing = [c for c in chosen if not prompts.has_culture(c)]
            if missing:
                raise ValueError(f"no culture prompt for {', '.join(missing)}; choose civs with --llm-civs")
            inner: llm.Adapter = llm.LiveAdapter(lambda civ, met: prompts.system_prompt(config, civ, met), models)
        else:
            inner = llm.MockAdapter({c: mock_ruler.make(config, c, state["seed"]) for c in chosen})
        recorder = llm.Recorder(inner, out / "outputs.jsonl" if out else None)
        adapter = recorder
        if resumed:  # stored answers up to the resume tick, then fresh calls, all counted by the recorder
            kept, resume_from = resumed[0], resumed[1]
            recorder.rows = list(kept)
            adapter = llm.Resumed(llm.ReplayAdapter(kept), recorder, resume_from, inner if mode == "mock" else None)
    for civ_id in chosen:
        deciders[civ_id] = llm.make_ruler(adapter, civ_id)
    return deciders, recorder


class Watch:
    """What the runner notes about each civ as the run goes. It reads state; it never changes it."""

    def __init__(self, config: Config, state: dict) -> None:
        self.config = config
        self.civs = {civ_id: {"run_out": {res: None for res in config.civ(civ_id).short_of},
                              "peak_pop": 0, "peak_pop_tick": 0, "pop_at_100": None,
                              "food": [], "tree_done": None, "first_town": None}
                     for civ_id in sorted(state["civs"])}
        self.last_food = {civ_id: 0 for civ_id in self.civs}

    def after_tick(self, state: dict, now: int) -> None:
        for civ_id, notes in self.civs.items():
            civ = state["civs"][civ_id]
            for resource, tick in notes["run_out"].items():
                if tick is None and civ["stocks"][resource] == 0:
                    notes["run_out"][resource] = now
            pop = engine.civ_pop(state, civ_id) + units.people(state, civ_id)
            if pop > notes["peak_pop"]:
                notes["peak_pop"], notes["peak_pop_tick"] = pop, now
            if now == 100:
                notes["pop_at_100"] = pop
            produced = state["ledger"].get(f"{civ_id}:food:production", 0)
            notes["food"].append(produced - self.last_food[civ_id])
            self.last_food[civ_id] = produced
            if notes["tree_done"] is None and not techs.available(state, civ_id) and not civ["research"]["tech"]:
                notes["tree_done"] = now
            if notes["first_town"] is None and any(
                    s["civ"] == civ_id and not s["capital"] and s["stage"] in ("town", "city")
                    for s in state["settlements"].values()):
                notes["first_town"] = now

    def summary(self, state: dict) -> dict:
        result = {}
        for civ_id, notes in self.civs.items():
            food = notes["food"]
            averages = [sum(food[i - 3:i + 1]) // 4 for i in range(3, len(food))]
            result[civ_id] = {
                "run_out": notes["run_out"],
                "peak_pop": notes["peak_pop"], "peak_pop_tick": notes["peak_pop_tick"],
                "pop_at_100": notes["pop_at_100"],
                "peak_food_output": max(averages, default=0),
                "food_output_at_100": averages[96] if len(averages) > 96 else None,
                "tree_done": notes["tree_done"], "first_town": notes["first_town"],
                "techs": len(state["civs"][civ_id]["techs"]),
                "stages": [e for e in state["events"] if e["kind"] == "stage" and e["civ"] == civ_id],
                "towns": {sid: {"name": s["name"], "stage": s["stage"], "pop": s["pop"],
                                "specialty": s["specialty"], "need": s["need"], "quirk": s["quirk"]}
                          for sid, s in sorted(state["settlements"].items()) if s["civ"] == civ_id},
            }
        return result


def play(config: Config, seed: int, ticks: int, bot: str = "builder", out: Path | None = None, *,
         mode: str = "bots", llm_civs: list[str] | None = None, outputs: Path | None = None,
         resumed: tuple[list[dict], int, int, str] | None = None,
         models: tuple[str, ...] | dict[str, str] = ROSTER) -> tuple[dict, dict]:
    """Run a world and return (final state, summary). With out, write the run folder as it goes.
    The folder must be new or empty: appending to an old run would mix two runs' logs and snapshots.
    resumed is for resume() only: (stored outputs to answer from, the tick fresh calls start at,
    a saved snapshot's tick and the state hash the replay must reach there). models is the list a
    live run's roster is drawn from, or a finished roster (a resumed run's)."""
    if out and not resumed and out.exists() and any(out.iterdir()):
        raise FileExistsError(f"run folder {out} is not empty; pick a new --out")
    state = worldgen.generate(config, seed)
    chosen = sorted(llm_civs or state["civs"])
    ruled = (dict(models) if isinstance(models, dict) else roster(tuple(models), chosen, seed)) if mode == "live" else {}
    deciders, recorder = rulers(config, state, bot, mode, llm_civs, outputs, out, resumed, ruled)  # refuses a bad setup first
    if out:
        out.mkdir(parents=True, exist_ok=True)
    watch = Watch(config, state)
    if out:
        manifest = {"seed": seed, "ticks": ticks, "bot": bot, "config_hash": config.config_hash(),
                    "events_enabled": config.events_enabled, "supply": config.supply_floor, "llm": mode,
                    "llm_civs": sorted(llm_civs or state["civs"]) if mode != "bots" else [],
                    "outputs": str(outputs) if outputs else None,
                    "models": ruled, "slice_pair": list(config.slice_pair)}
        if resumed:
            old = json.loads((out / "manifest.json").read_text(encoding="ascii"))
            manifest["resumed_at"] = old.get("resumed_at", []) + [resumed[1]]
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="ascii")
        snapshot.save(state, out / "snap-00000.json.gz")
    failing = Failing() if mode == "live" else None
    for _ in range(ticks):
        now = state["tick"]
        if resumed and now == resumed[2] and state_hash(state) != resumed[3]:
            raise llm.ReplayError(f"the replayed world at tick {now} differs from the snapshot saved there")
        log: list | None = [] if out else None
        seen_rows = len(recorder.rows) if recorder else 0
        records = engine.tick(config, state, log, deciders=deciders)
        if failing and recorder:
            failing.after(recorder.rows[seen_rows:])
        watch.after_tick(state, now)
        if out:
            snapshot.append_lines(out / "ledger.jsonl", log)
            snapshot.append_lines(out / "turns.jsonl", [r.as_record() for r in records])
            if state["tick"] % config.snapshot_every == 0:
                snapshot.save(state, out / f"snap-{state['tick']:05d}.json.gz")
    if out and state["tick"] % config.snapshot_every:  # the last tick too, so a check can read where the run ended
        snapshot.save(state, out / f"snap-{state['tick']:05d}.json.gz")
    summary = watch.summary(state)
    if recorder:
        for civ_id, calls in recorder.usage().items():
            summary[civ_id]["calls"] = calls
        for civ_id, spent in recorder.tokens().items():
            summary[civ_id]["tokens"] = spent
        for civ_id, metered in cost_meter(recorder.rows, state, 0, state["tick"], ruled).items():
            summary[civ_id]["cost"] = metered
    if out:
        (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    return state, summary


def resume_point(rows: list[dict]) -> int:
    """The tick a stopped run carries on from. The last tick with stored outputs may have stopped
    half way, and a run stopped by failures ends in ticks where every call failed (run out of plan
    usage, say), so those are played again with fresh calls rather than replayed as empty turns."""
    by_tick: dict[int, set[str]] = {}
    for row in rows:
        by_tick.setdefault(row["tick"], set()).add(row["status"])
    ticks = sorted(by_tick)
    if not ticks:
        return 0
    i = len(ticks) - 1
    while i > 0 and llm.OK not in by_tick[ticks[i - 1]]:
        i -= 1
    return ticks[i]


def resume(out: Path) -> tuple[dict, dict]:
    """Carry on a stopped live or mock run in its own folder. Its stored outputs before the resume
    tick are replayed from tick 0, each checked against the observation it answered, and the state
    at the last snapshot before that tick must match the one saved; from the resume tick on, the
    rulers are called afresh. The logs and snapshots are written again as the replay goes."""
    manifest = json.loads((out / "manifest.json").read_text(encoding="ascii"))
    if manifest["llm"] not in ("mock", "live"):
        raise ValueError(f"only a mock or live run can be resumed, not {manifest['llm']}")
    config = dataclasses.replace(Config(), events_enabled=manifest["events_enabled"],
                                 supply_floor=manifest["supply"], slice_pair=tuple(manifest["slice_pair"]))
    if config.config_hash() != manifest["config_hash"]:
        raise ValueError("the config has changed since this run started, so it can't be resumed")
    rows = _outputs_up_to_a_torn_line(out / "outputs.jsonl")
    resume_from = resume_point(rows)
    rows = sorted(rows, key=lambda r: r["tick"])  # stable, so calls within a tick keep their order
    kept = [r for r in rows if r["tick"] < resume_from]
    checkpoint = max((int(p.name[5:10]) for p in out.glob("snap-*.json.gz") if int(p.name[5:10]) <= resume_from),
                     default=0)
    expected = state_hash(snapshot.load(out / f"snap-{checkpoint:05d}.json.gz"))

    # The stopped session's files go into an archive, outputs included, so no paid call is lost.
    archive = out / f"before-resume-{len(manifest.get('resumed_at', [])) + 1}"
    archive.mkdir()
    moved = [p for p in [*out.glob("snap-*.json.gz"), *(out / n for n in RUN_LOGS)] if p.exists()]
    for path in moved:
        path.rename(archive / path.name)
    with open(out / "outputs.jsonl", "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r, sort_keys=True) + "\n" for r in kept)
    try:
        state, summary = play(config, manifest["seed"], manifest["ticks"], manifest["bot"], out, mode=manifest["llm"],
                              llm_civs=manifest["llm_civs"], resumed=(kept, resume_from, checkpoint, expected),
                              models=manifest_models(manifest))
    except llm.ReplayError:  # nothing fresh was called yet, so put the stopped session back as it was
        for path in [*out.glob("snap-*.json.gz"), *(out / n for n in RUN_LOGS)]:
            path.unlink(missing_ok=True)
        for path in moved:
            (archive / path.name).rename(path)
        archive.rmdir()
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="ascii")
        raise
    ruled = manifest_models(manifest)
    for row in rows[len(kept):]:  # calls made and paid for, then dropped to be made again
        dropped = summary.setdefault(row["civ"], {}).setdefault("dropped_on_resume", {"calls": 0, "cost_usd": 0.0})
        dropped["calls"] += 1
        price = pricing.row_cost(row, ruled.get(row["civ"], pricing.DEFAULT_MODEL))
        dropped["cost_usd"] = round(dropped["cost_usd"] + price, 4)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    return state, summary


def manifest_models(manifest: dict) -> dict[str, str]:
    """A run's roster as its manifest records it. Runs from before the roster named one model
    for every ruler, or none (claude-haiku-5-5)."""
    if manifest.get("models"):
        return dict(manifest["models"])
    if manifest.get("llm") != "live":
        return {}
    return {civ: manifest.get("model") or pricing.DEFAULT_MODEL for civ in manifest.get("llm_civs", [])}


RUN_LOGS = ("outputs.jsonl", "turns.jsonl", "ledger.jsonl", "summary.json")


def _outputs_up_to_a_torn_line(path: Path) -> list[dict]:
    """Stored outputs, without a last line cut off half way when the run was killed mid-write."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    for number, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if number < len(lines) - 1:
                raise
    return rows


def _print(summary: dict, state: dict) -> None:
    print(f"tick {state['tick']}  state {state_hash(state)[:16]}")
    for civ_id, row in summary.items():
        run_out = ", ".join(f"{res} at {tick}" if tick is not None else f"{res} never"
                            for res, tick in row["run_out"].items())
        print(f"\n{civ_id}: ran out of {run_out}; peak pop {row['peak_pop']} at tick {row['peak_pop_tick']}, "
              f"{row['pop_at_100']} at tick 100; food output peak {row['peak_food_output']}, "
              f"{row['food_output_at_100']} at tick 100")
        print(f"  techs {row['techs']}, tree done {row['tree_done']}, first town {row['first_town']}")
        if "calls" in row:
            print("  ruler calls " + ", ".join(f"{status} {n}" for status, n in row["calls"].items()))
        for event in row["stages"]:
            print(f"  tick {event['tick']}: {event['detail']}")
        for sid, town in row["towns"].items():
            print(f"  {sid} {town['name']}: {town['stage']}, pop {town['pop']}, strong {town['specialty']['strong']}, "
                  f"weak {town['specialty']['weak']}, needs {town['need']}, quirk {town['quirk']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a Fogline world headless.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=1000)
    parser.add_argument("--bot", choices=sorted(BOTS), default="builder")
    parser.add_argument("--no-events", action="store_true", help="turn Providence events off")
    parser.add_argument("--supply", type=int, default=0,
                        help="test-only top-up of basics each tick (ADR 0004); 0 is off")
    parser.add_argument("--out", type=Path, help="write a run folder here, for example runs/seed1")
    parser.add_argument("--llm", choices=LLM_MODES, default="bots",
                        help="bots: scripted only; mock: bots through the text adapter; replay: stored outputs; "
                             "live: claude -p")
    parser.add_argument("--llm-civs", help="comma-separated civs the --llm mode applies to (default: all)")
    parser.add_argument("--outputs", type=Path, help="outputs.jsonl to replay")
    parser.add_argument("--models", help="comma-separated models a live run's rulers are drawn from, rotated by "
                                          f"seed (default: {','.join(ROSTER)}); one model rules every civ")
    parser.add_argument("--resume", type=Path, metavar="FOLDER",
                        help="carry on a stopped mock or live run in its own folder; other options are read "
                             "from its manifest")
    parser.add_argument("--slice", action="store_true",
                        help="Phase 3b slice: Verdance and Saltreach start as neighbours and meet at once; "
                             "the other civs trade as scripted bots")
    args = parser.parse_args()
    config = dataclasses.replace(Config(), events_enabled=not args.no_events, supply_floor=args.supply,
                                 slice_pair=SLICE_PAIR if args.slice else ())
    if args.slice and args.bot == "builder":
        args.bot = "trader"  # the slice's scripted neighbours trade
    llm_civs = [c.strip() for c in args.llm_civs.split(",")] if args.llm_civs else None
    try:
        if args.resume:
            state, summary = resume(args.resume)
        else:
            models = tuple(m.strip() for m in args.models.split(",")) if args.models else ROSTER
            state, summary = play(config, args.seed, args.ticks, args.bot, args.out, mode=args.llm,
                                  llm_civs=llm_civs, outputs=args.outputs, models=models)
    except (FileExistsError, ValueError, llm.ReplayError, llm.LiveFailure, pricing.UnknownModel) as error:
        parser.error(str(error))
    _print(summary, state)


if __name__ == "__main__":
    main()
