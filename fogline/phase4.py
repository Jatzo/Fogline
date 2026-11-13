"""The Phase 4 checks, read from a finished run folder: python -m fogline.phase4 runs/<name>

PLAN section 15, Phase 4: the run reached its last tick, every civ built at least 3 building
types, and the rulers' action mixes differ by at least the threshold in rules section 18. First
contact is reported for each civ, not required: LLM rulers may scout more or less than the
scripted scouts the contact-timing test uses. It reads the folder and changes nothing.
"""

import argparse
import json
import math
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

from fogline import snapshot

DIVERGENCE_THRESHOLD = 0.05  # rules 18: mean pairwise Jensen-Shannon divergence, base 2
MIN_BUILDING_TYPES = 3
SNAPSHOT_NAME = re.compile(r"snap-(\d{5})\.json\.gz")


def applied_actions(record: dict) -> Counter:
    """The action kinds a decide turn actually carried out: every action it sent that no rejection
    names by its index. A reply that never parsed is stored as None and carried out nothing."""
    reply = record.get("reply")
    if record.get("step") != "decide" or not isinstance(reply, dict) or not isinstance(reply.get("actions"), list):
        return Counter()
    refused = {r.get("index") for r in record.get("rejections") or []}
    return Counter(action["kind"] for index, action in enumerate(reply["actions"])
                   if index not in refused and isinstance(action, dict) and isinstance(action.get("kind"), str))


def jensen_shannon(first: Counter, second: Counter) -> float:
    """Divergence of two histograms, base 2, so 0 means the same mix and 1 means no kind in common."""
    total_a, total_b = sum(first.values()), sum(second.values())
    if not total_a or not total_b:
        raise ValueError("a histogram with no actions has no mix to compare")
    divergence = 0.0
    for kind in sorted(set(first) | set(second)):
        p, q = first[kind] / total_a, second[kind] / total_b
        m = (p + q) / 2
        divergence += (p * math.log2(p / m) if p else 0.0) + (q * math.log2(q / m) if q else 0.0)
    return divergence / 2


def building_types(events: list[dict], civ_id: str) -> list[str]:
    """Every building type the civ finished in the run, from its "built" events."""
    return sorted({e["detail"].split()[1] for e in events if e["kind"] == "built" and e["civ"] == civ_id})


def check(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="ascii"))
    snaps = sorted(p for p in folder.glob("snap-*.json.gz") if SNAPSHOT_NAME.fullmatch(p.name))
    if not snaps:
        raise FileNotFoundError(f"{folder} has no snapshots")
    state = snapshot.load(snaps[-1])
    with open(folder / "turns.jsonl", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    llm_civs = manifest["llm_civs"]
    mixes = {civ_id: Counter() for civ_id in llm_civs}
    for record in records:
        if record["civ"] in mixes:
            mixes[record["civ"]] += applied_actions(record)
    acting = [c for c in llm_civs if mixes[c]]
    pairs = {f"{a} {b}": round(jensen_shannon(mixes[a], mixes[b]), 4) for a, b in combinations(acting, 2)}
    divergence = round(sum(pairs.values()) / len(pairs), 4) if pairs else None

    civs = {}
    for civ_id in sorted(state["civs"]):
        met = state["civs"][civ_id]["met"]
        civs[civ_id] = {"building_types": building_types(state["events"], civ_id),
                        "first_contact": min(met.values()) if met else None,
                        "actions": dict(sorted(mixes[civ_id].items())) if civ_id in mixes else None}
    passed = {
        "reached_last_tick": state["tick"] >= manifest["ticks"],
        "building_types": all(len(c["building_types"]) >= MIN_BUILDING_TYPES for c in civs.values()),
        "divergence": divergence is not None and len(acting) == len(llm_civs) and divergence >= DIVERGENCE_THRESHOLD,
    }
    return {"tick": state["tick"], "ticks": manifest["ticks"], "llm_civs": llm_civs, "divergence": divergence,
            "pair_divergence": pairs, "civs": civs, "passed": passed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a finished run against the Phase 4 'done when'.")
    parser.add_argument("folder", type=Path)
    result = check(parser.parse_args().folder)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if all(result["passed"].values()) else 1)


if __name__ == "__main__":
    main()
