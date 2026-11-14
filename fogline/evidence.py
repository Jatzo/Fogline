"""An evidence pack on how each ruler model behaved, progressed and learned, read from run folders:
python -m fogline.evidence runs/p4-mix-s1 runs/p4-mix-s2 runs/p4-mix-s3 --out research/<name>.md

Numbers, tables and short excerpts of the rulers' own strategy text, picked by a fixed rule; no
conclusions (CLAUDE.md: the narrative is the operator's). Every row names the civ and its model
together, because within one seed a model's effect and a culture's can't be told apart. It reads
the folders and changes nothing; it reads snapshots, the ground truth, on purpose: this is the
operator's analysis, and nothing it writes reaches a ruler.
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fogline import phase4, pricing, snapshot
from fogline.run import manifest_models, read_jsonl

WINDOW = 50                    # ticks per row in the progress and refusal tables
EXCERPT_TICKS = (8, 100, 200, 300, 400)
EXCERPT_CHARS = 200
MIN_FOR_SHARE = 10             # fewer proposals than this show counts only, never a percentage


@dataclass
class Run:
    name: str
    manifest: dict
    models: dict[str, str]
    records: list[dict]          # turns.jsonl
    outputs: list[dict]          # outputs.jsonl
    snaps: dict[int, Path]       # tick -> snapshot file
    final: dict                  # the last snapshot's state

    def model(self, civ: str) -> str:
        return short(self.models.get(civ, self.manifest.get("llm") or "bot"))

    def contact(self, civ: str) -> int | None:
        """The first turn that could see contact (rules: contact at tick t is first seen at t + 1)."""
        return self.final["civs"][civ].get("first_contact_turn")


def short(model: str) -> str:
    return model.replace("claude-", "").replace("-5-5", " 5.5").capitalize()


def load(folder: Path) -> Run:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="ascii"))
    snaps = {int(m.group(1)): p for p in folder.glob("snap-*.json.gz") if (m := phase4.SNAPSHOT_NAME.fullmatch(p.name))}
    if not snaps:
        raise FileNotFoundError(f"{folder} has no snapshots")
    final = snapshot.load(snaps[max(snaps)])
    # A run still playing logs every tick but snapshots every few; rows past the last snapshot are left
    # out, so every table covers the same ticks.
    logs = [[row for row in (read_jsonl(folder / name) if (folder / name).is_file() else []) if row["tick"] <= final["tick"]]
            for name in ("turns.jsonl", "outputs.jsonl")]
    return Run(folder.name, manifest, manifest_models(manifest), *logs, snaps, final)


def snap_at(run: Run, tick: int) -> tuple[int, dict]:
    """The snapshot at or before a tick, with the tick it was taken."""
    taken = max(t for t in run.snaps if t <= tick)
    return taken, (run.final if taken == max(run.snaps) else snapshot.load(run.snaps[taken]))


def civ_figures(state: dict, civ: str) -> dict:
    mine = [s for s in state["settlements"].values() if s["civ"] == civ]
    stages = Counter(s["stage"] for s in mine)
    c = state["civs"][civ]
    return {"pop": sum(s["pop"] for s in mine), "techs": len(c["techs"]), "stability": c["stability"],
            "settlements": ", ".join(f"{n} {stage}" for stage, n in sorted(stages.items())) or "none",
            "stocks": " / ".join(str(c["stocks"].get(g, 0)) for g in ("food", "timber", "stone", "metal"))}


def proposed(record: dict) -> int:
    reply = record.get("reply")
    if record.get("step") != "decide" or not isinstance(reply, dict) or not isinstance(reply.get("actions"), list):
        return 0
    return len(reply["actions"])


def refused(record: dict) -> list[dict]:
    """Refusals of the turn's own actions; a refused end_turn (index -1) isn't an action."""
    return [r for r in record.get("rejections") or [] if isinstance(r.get("index"), int) and r["index"] >= 0]


def trade_answers(record: dict) -> Counter:
    reply, gone = record.get("reply"), {r["index"] for r in refused(record)}
    answers = Counter()
    if isinstance(reply, dict) and isinstance(reply.get("actions"), list):
        for index, action in enumerate(reply["actions"]):
            if index not in gone and isinstance(action, dict) and action.get("kind") == "respond_trade":
                answers["accepted" if action.get("accept") else "declined"] += 1
    return answers


def opening(text: str) -> str:
    """The first EXCERPT_CHARS characters, cut at a word. A fixed cut rather than the first sentence:
    some rulers open every strategy with a date stamp."""
    text = " ".join(str(text).split()).replace("`", "'")
    if len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


def stretches(end: int) -> list[tuple[int, int]]:
    """WINDOW-tick stretches from 0, the last running to the final tick inclusive."""
    starts = list(range(0, end, WINDOW)) or [0]
    return [(low, starts[i + 1] if i + 1 < len(starts) else end + 1) for i, low in enumerate(starts)]


def rate(count: float, per: float) -> str:
    return f"{count / per:.2f}" if per else "n/a"


def share(part: int, whole: int) -> str:
    return f"{part}/{whole}" + (f" ({100 * part / whole:.0f}%)" if whole >= MIN_FOR_SHARE else "")


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows), ""]


def run_section(run: Run) -> list[str]:
    civs = sorted(run.manifest["llm_civs"])
    end = run.final["tick"]
    decide = {c: [r for r in run.records if r["civ"] == c and r["step"] == "decide"] for c in civs}
    reflect = {c: [r for r in run.records if r["civ"] == c and r["step"] == "reflect"] for c in civs}
    label = {c: f"{c.capitalize()} ({run.model(c)})" for c in civs}
    out = [f"## {run.name}", "",
           f"Seed {run.manifest['seed']}, reached tick {end} of {run.manifest['ticks']}. "
           f"Rulers: " + ", ".join(label[c] for c in civs) + ".", ""]

    out += [f"### Progress (snapshot at or before every {WINDOW} ticks)", ""]
    ticks = sorted({snap_at(run, t)[0] for t in range(0, end + 1, WINDOW)} | {end})
    states = {t: snap_at(run, t)[1] for t in ticks}
    for c in civs:
        rows, gone = [], None
        for t in ticks:
            f = civ_figures(states[t], c)
            if f["settlements"] == "none" and gone is None:
                gone = t
            rows.append([t, f["pop"], f["techs"], f["stability"], f["settlements"], f["stocks"]])
        out += [f"**{label[c]}**, first turn after contact: {run.contact(c) if run.contact(c) is not None else 'no contact'}"
                + (f"; no settlements from tick {gone}" if gone is not None else ""), ""]
        out += table(["Tick", "People", "Techs", "Stability", "Settlements", "Food / timber / stone / metal"], rows)

    out += ["### Behaviour, before and after contact", "",
            "Applied actions only (refused ones are left out). Rates are per tick of each civ's own window.", ""]
    rows = []
    for c in civs:
        seen = run.contact(c)
        windows = [("before", 0, seen), ("after", seen, end + 1)] if seen is not None else [("whole run, no contact", 0, end + 1)]
        for name, low, high in windows:
            turns = [r for r in decide[c] if low <= r["tick"] < high]
            mix = sum((phase4.applied_actions(r) for r in turns), Counter())
            answers = sum((trade_answers(r) for r in turns), Counter())
            span = max(0, min(high, end + 1) - low)
            rows.append([label[c], name, span, len(turns), rate(len(turns), span), sum(mix.values()),
                         rate(sum(mix.values()), span), rate(mix["send_message"], span), mix["offer_trade"],
                         answers["accepted"], answers["declined"], mix["build"], mix["set_note"]])
    out += table(["Civ", "Window", "Ticks", "Decide turns", "Turns per tick", "Actions", "Actions per tick",
                  "Messages per tick", "Offers made", "Offers accepted", "Offers declined", "Builds", "Notes"], rows)

    rows = []
    for c in civs:
        mix = sum((phase4.applied_actions(r) for r in decide[c]), Counter())
        kinds = ", ".join(f"{k} {n}" for k, n in mix.most_common())
        built = ", ".join(phase4.building_types(run.final["events"], c)) or "none"
        half = [sum((phase4.applied_actions(r) for r in decide[c] if (r["tick"] < end / 2) == early), Counter())
                for early in (True, False)]
        drift = f"{phase4.jensen_shannon(*half):.3f}" if all(half) else "n/a"
        rows.append([label[c], kinds or "none", built, drift])
    out += table(["Civ", "Applied actions by kind", "Building types finished", "Mix change, first vs second half"], rows)

    out += [f"### Learning: refused actions per {WINDOW} ticks", "",
            "Refused / proposed actions in each window; a share is shown only from "
            f"{MIN_FOR_SHARE} proposals up.", ""]
    rows = []
    for c in civs:
        cells = []
        for low, high in stretches(end):
            turns = [r for r in decide[c] if low <= r["tick"] < high]
            cells.append(share(sum(len(refused(r)) for r in turns), sum(proposed(r) for r in turns)))
        reasons = Counter(r.get("reason", "?") for t in decide[c] for r in refused(t))
        rows.append([label[c], *cells, ", ".join(f"{k} {n}" for k, n in reasons.most_common(3)) or "none"])
    out += table(["Civ", *(f"{low}-{high - 1}" for low, high in stretches(end)),
                  "Top refusal reasons"], rows)

    rows = []
    for c in civs:
        eligible = repeated = 0
        for before, after in zip(decide[c], decide[c][1:]):
            kinds = {r.get("kind") for r in refused(before)}
            if kinds:
                eligible += 1
                repeated += bool(kinds & {r.get("kind") for r in refused(after)})
        strategies = [r["reply"] for r in reflect[c] if isinstance(r.get("reply"), str)]
        changed = sum(a != b for a, b in zip(strategies, strategies[1:]))
        rows.append([label[c], f"{repeated}/{eligible}", len(reflect[c]), changed,
                     sum(phase4.applied_actions(r)["set_note"] for r in decide[c])])
    out += table(["Civ", "Refused kind refused again next turn (of turns after a refusal)", "Reflections",
                  "Reflections that changed the strategy text", "Notes written"], rows)

    out += ["### Learning: strategy text over time", "",
            f"The opening {EXCERPT_CHARS} characters of the reflection at or before each tick; "
            "the tick it was written is given. Ruler text, quoted as data.", ""]
    for c in civs:
        out.append(f"**{label[c]}**")
        out.append("")
        for at in EXCERPT_TICKS:
            written = [r for r in reflect[c] if r["tick"] <= at and isinstance(r.get("reply"), str)]
            if written:
                out += [f"Tick {written[-1]['tick']}:", "```text", opening(written[-1]["reply"]), "```"]
        out.append("")

    out += ["### Effort and cost", "",
            "Every stored call, failed ones included, priced at list prices (`fogline/pricing.py`).", ""]
    rows = []
    for c in civs:
        calls = [r for r in run.outputs if r["civ"] == c]
        priced = [r for r in calls if r.get("usage")]
        tokens = sum(r["usage"].get("output_tokens", 0) for r in priced)
        cost = sum(pricing.row_cost(r, run.models.get(c, pricing.DEFAULT_MODEL)) for r in priced)
        unparsed = sum(1 for r in run.records if r["civ"] == c and r.get("reply") is None)
        rows.append([label[c], len(calls), sum(r["status"] != "ok" for r in calls), unparsed,
                     rate(len(calls), end + 1), rate(tokens, len(priced)).split(".")[0] if priced else "n/a",
                     f"${cost:.2f}", f"${cost / (end + 1):.3f}"])
    out += table(["Civ", "Calls", "Failed", "Replies that never parsed", "Calls per tick",
                  "Output tokens per call", "Cost", "Cost per tick"], rows)
    return out


def model_section(runs: list[Run]) -> list[str]:
    """Pooled per model: sums over its civs, divided by their summed ticks or proposals."""
    pool: dict[str, Counter] = {}
    cells: dict[str, list[str]] = {}
    for run in runs:
        span = run.final["tick"] + 1
        for c in sorted(run.manifest["llm_civs"]):
            m = run.model(c)
            cells.setdefault(m, []).append(f"{c} seed {run.manifest['seed']}")
            p = pool.setdefault(m, Counter())
            turns = [r for r in run.records if r["civ"] == c and r["step"] == "decide"]
            mix = sum((phase4.applied_actions(r) for r in turns), Counter())
            p["ticks"] += span
            p["calls"] += sum(1 for r in run.outputs if r["civ"] == c)
            p["actions"] += sum(mix.values())
            p["messages"] += mix["send_message"]
            p["builds"] += mix["build"]
            p["proposed"] += sum(proposed(r) for r in turns)
            p["refused"] += sum(len(refused(r)) for r in turns)
            p["cost"] += sum(pricing.row_cost(r, run.models.get(c, pricing.DEFAULT_MODEL))
                             for r in run.outputs if r["civ"] == c and r.get("usage"))
    rows = [[m, len(cells[m]), "; ".join(cells[m]), rate(p["calls"], p["ticks"]), rate(p["actions"], p["ticks"]),
             rate(p["messages"], p["ticks"]), rate(p["builds"] * 100, p["ticks"]), share(p["refused"], p["proposed"]),
             f"${p['cost'] / p['ticks'] * 100:.2f}"] for m, p in sorted(pool.items())]
    return ["## Across runs, pooled per model", "",
            "Sums over each model's civs, divided by their summed ticks. Each model ruled different cultures "
            "in different seeds, listed beside it.", "",
            *table(["Model", "Civs", "Which", "Calls per tick", "Actions per tick", "Messages per tick",
                    "Builds per 100 ticks", "Refused of proposed", "Cost per 100 ticks"], rows)]


def pack(runs: list[Run]) -> str:
    names = " ".join(f"runs/{r.name}" for r in runs)
    lines = ["# How the ruler models behaved, progressed and learned (evidence draft)", "",
             f"Numbers only, generated by `python -m fogline.evidence {names}`. It draws no conclusions; the "
             "reading is the operator's. Within one seed each model rules one or two cultures, so a model's figures "
             "and its cultures' can't be told apart.", ""]
    for run in runs:
        lines += run_section(run)
    if len(runs) > 1:
        lines += model_section(runs)
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an evidence pack on the ruler models from run folders.")
    parser.add_argument("folders", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, help="markdown file to write (default: print)")
    args = parser.parse_args()
    text = pack([load(folder) for folder in args.folders])
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
