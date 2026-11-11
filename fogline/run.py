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

from fogline import bots, engine, llm, prompts, snapshot, techs, units, worldgen
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
SLICE_PAIR = ("verdance", "saltreach")  # Phase 3b (operator's choice, rules 21)
FAILED_TICKS_TO_STOP = {llm.ERROR: 3, llm.TIMEOUT: 5}  # ticks in a row where every live call failed


def cost_meter(rows: list[dict], state: dict, start_tick: int, end_tick: int) -> dict[str, dict]:
    """Per civ: calls, tokens and cost before and after its first contact, each also per 100 ticks
    of that stretch, with the call counts behind every figure (PLAN section 10, Phase 3b)."""
    meter = {}
    for civ_id in sorted({r["civ"] for r in rows}):
        met = state["civs"][civ_id]["met"]
        contact = min(met.values()) if met else end_tick
        spans = {"before_contact": (start_tick, contact), "after_contact": (contact, end_tick)}
        meter[civ_id] = {"first_contact": min(met.values()) if met else None}
        for name, (low, high) in spans.items():
            mine = [r for r in rows if r["civ"] == civ_id and low <= r["tick"] < high]
            spent = {"ticks": high - low, "calls": len(mine), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            for row in mine:
                usage = row.get("usage") or {}
                spent["input_tokens"] += usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)                     + usage.get("cache_read_input_tokens", 0)
                spent["output_tokens"] += usage.get("output_tokens", 0)
                spent["cost_usd"] += usage.get("total_cost_usd", 0.0)
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
           outputs: Path | None, out: Path | None) -> tuple[dict, llm.Recorder | None]:
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
            inner: llm.Adapter = llm.LiveAdapter(lambda civ, met: prompts.system_prompt(config, civ, met))
        else:
            inner = llm.MockAdapter({c: mock_ruler.make(config, c, state["seed"]) for c in chosen})
        recorder = llm.Recorder(inner, out / "outputs.jsonl" if out else None)
        adapter = recorder
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
         mode: str = "bots", llm_civs: list[str] | None = None, outputs: Path | None = None) -> tuple[dict, dict]:
    """Run a world and return (final state, summary). With out, write the run folder as it goes.
    The folder must be new or empty: appending to an old run would mix two runs' logs and snapshots."""
    if out and out.exists() and any(out.iterdir()):
        raise FileExistsError(f"run folder {out} is not empty; pick a new --out")
    state = worldgen.generate(config, seed)
    deciders, recorder = rulers(config, state, bot, mode, llm_civs, outputs, out)  # refuses a bad setup first
    if out:
        out.mkdir(parents=True, exist_ok=True)
    watch = Watch(config, state)
    if out:
        manifest = {"seed": seed, "ticks": ticks, "bot": bot, "config_hash": config.config_hash(),
                    "events_enabled": config.events_enabled, "supply": config.supply_floor, "llm": mode,
                    "llm_civs": sorted(llm_civs or state["civs"]) if mode != "bots" else [],
                    "outputs": str(outputs) if outputs else None,
                    "model": llm.MODEL if mode == "live" else None, "slice_pair": list(config.slice_pair)}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="ascii")
        snapshot.save(state, out / "snap-00000.json.gz")
    failing = Failing() if mode == "live" else None
    for _ in range(ticks):
        now = state["tick"]
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
    summary = watch.summary(state)
    if recorder:
        for civ_id, calls in recorder.usage().items():
            summary[civ_id]["calls"] = calls
        for civ_id, spent in recorder.tokens().items():
            summary[civ_id]["tokens"] = spent
        for civ_id, metered in cost_meter(recorder.rows, state, 0, state["tick"]).items():
            summary[civ_id]["cost"] = metered
    if out:
        (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    return state, summary


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
        state, summary = play(config, args.seed, args.ticks, args.bot, args.out, mode=args.llm,
                              llm_civs=llm_civs, outputs=args.outputs)
    except (FileExistsError, ValueError, llm.ReplayError, llm.LiveFailure) as error:
        parser.error(str(error))
    _print(summary, state)


if __name__ == "__main__":
    main()
