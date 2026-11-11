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

from fogline import bots, engine, llm, snapshot, techs, units, worldgen
from fogline.config import Config
from fogline.state import state_hash

BOTS = {"builder": lambda config, civ_id: bots.make_builder(config, "food" in config.civ(civ_id).short_of),
        "spiral": lambda config, civ_id: bots.spiral_scout, "idle": lambda config, civ_id: bots.idle}


def deciders_for(config: Config, state: dict, bot: str = "builder") -> dict:
    """One scripted ruler per civ."""
    return {civ_id: BOTS[bot](config, civ_id) for civ_id in sorted(state["civs"])}


LLM_MODES = ("bots", "mock", "replay", "live")


def rulers(config: Config, state: dict, bot: str, mode: str, llm_civs: list[str] | None,
           outputs: Path | None, prompt: str | None, out: Path | None) -> tuple[dict, llm.Recorder | None]:
    """The deciders for a run, and the recorder if outputs are being kept.

    bots: every civ is a scripted bot, called directly. mock: the chosen civs' bots speak through
    the text adapter, as an LLM would. replay: the chosen civs answer from stored outputs. live: the
    chosen civs call `claude -p` with the given system prompt. Civs not chosen stay scripted bots.
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
        if mode == "live" and (not prompt or out is None):
            raise ValueError("--llm live needs --prompt and --out, so every call is kept")
        inner = llm.MockAdapter({c: deciders[c] for c in chosen}) if mode == "mock" else llm.LiveAdapter(prompt)
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
         mode: str = "bots", llm_civs: list[str] | None = None, outputs: Path | None = None,
         prompt: str | None = None) -> tuple[dict, dict]:
    """Run a world and return (final state, summary). With out, write the run folder as it goes.
    The folder must be new or empty: appending to an old run would mix two runs' logs and snapshots."""
    if out and out.exists() and any(out.iterdir()):
        raise FileExistsError(f"run folder {out} is not empty; pick a new --out")
    state = worldgen.generate(config, seed)
    if out:
        out.mkdir(parents=True, exist_ok=True)
    deciders, recorder = rulers(config, state, bot, mode, llm_civs, outputs, prompt, out)
    watch = Watch(config, state)
    if out:
        manifest = {"seed": seed, "ticks": ticks, "bot": bot, "config_hash": config.config_hash(),
                    "events_enabled": config.events_enabled, "supply": config.supply_floor, "llm": mode,
                    "llm_civs": sorted(llm_civs or state["civs"]) if mode != "bots" else [],
                    "outputs": str(outputs) if outputs else None,
                    "model": llm.MODEL if mode == "live" else None}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="ascii")
        snapshot.save(state, out / "snap-00000.json.gz")
    for _ in range(ticks):
        now = state["tick"]
        log: list | None = [] if out else None
        records = engine.tick(config, state, log, deciders=deciders)
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
    parser.add_argument("--prompt", type=Path, help="system prompt file for --llm live")
    args = parser.parse_args()
    config = dataclasses.replace(Config(), events_enabled=not args.no_events, supply_floor=args.supply)
    llm_civs = [c.strip() for c in args.llm_civs.split(",")] if args.llm_civs else None
    prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else None
    try:
        state, summary = play(config, args.seed, args.ticks, args.bot, args.out, mode=args.llm,
                              llm_civs=llm_civs, outputs=args.outputs, prompt=prompt)
    except (FileExistsError, ValueError, llm.ReplayError) as error:
        parser.error(str(error))
    _print(summary, state)


if __name__ == "__main__":
    main()
