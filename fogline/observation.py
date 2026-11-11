"""The single gate between ground truth and a ruler (PLAN section 7, ADR 0006).

observe() is the only code that reads state for a ruler. Every key it may emit is listed in
FIELDS, and check_fields() fails loudly on anything else, so a new field has to be added here on
purpose. Tiles are "dx,dy" from the civ's origin; another civ appears only by name, and only once
it is met; nothing states the map size or how many civs there are.
"""

import re
from collections.abc import Mapping
from typing import Any

from fogline import memory, reputation, rules, sight, techs, units
from fogline.config import Config
from fogline.intmath import PER_MILLE, floor_div
from fogline.state import canonical_json, parse_tile_key, tile_key

MAX_CHARS = 12_000  # about 3,000 tokens of canonical JSON (PLAN section 7)
NEAR = 6  # known tiles this close to an own settlement or unit survive a trim

# The whitelist. A value is a type, a nested mapping (an object with exactly these keys),
# [spec] for a list of spec, or {str: spec} for an object with free keys.
_TRIGGER = {"trigger": str, "detail": str}
_REJECTION = {"index": int, "kind": str, "reason": str}
_EVENT = {"tick": int, "kind": str, "detail": str}
FIELDS: Mapping[str, Any] = {
    "tick": int,
    "season": str,
    "triggers": [_TRIGGER],
    "rejections": [_REJECTION],
    "stocks": {str: int},
    "stock_changes": {str: int},
    "population": int,
    "score": int,
    "stability": int,
    "techs": [str],
    "allocation": {str: int},
    "reorders": [{"stock": str, "below": int, "workers": int}],
    "research": {"tech": str, "points": int, "available": [{"tech": str, "hint": str}]},
    "build_queue": [{"settlement": str, "building": str, "mode": str, "tile": str, "started": bool,
                     "ticks_left": int}],
    "settlements": [{"id": str, "name": str, "tile": str, "stage": str, "pop": int, "buildings": [str]}],
    "units": [{"id": str, "kind": str, "pop": int, "tile": str, "ready": bool, "target": str}],
    "known": {str: str},
    "known_elsewhere": {str: int},
    "nodes": [{"id": str, "kind": str, "tile": str, "settlement": str, "left": int, "worked": bool}],
    "in_view": [{"civ": str, "kind": str, "tile": str}],
    "foreign_sites": [{"civ": str, "tile": str}],
    "met": [{"name": str, "standing": str}],
    "events": [_EVENT],
    "journal": [{"tick": int, "text": str, "source": str, "about": str}],
    "messages": [{"from": str, "sent": int, "hearsay": bool, "text": str}],
    "strategy": str,
    "elided": [str],
}

_TILE = re.compile(r"^-?\d+,-?\d+$")
_PUNCTUATION = "()[]{}<>.,;:!?'\"`"

# Shown only once the civ has met someone. Before that even an empty list, or a key named
# foreign_sites, would tell a ruler that other peoples exist.
AFTER_CONTACT = frozenset({"in_view", "foreign_sites", "met", "messages"})


class ObservationError(ValueError):
    """Raised when an observation holds a key or type the whitelist doesn't allow."""


def check_fields(value: Any, spec: Any = FIELDS, path: str = "observation") -> None:
    """Fail loudly unless value matches the whitelist exactly."""
    if isinstance(spec, list):
        if not isinstance(value, list):
            raise ObservationError(f"{path} must be a list")
        for index, item in enumerate(value):
            check_fields(item, spec[0], f"{path}[{index}]")
    elif isinstance(spec, Mapping) and set(spec) == {str}:
        if not isinstance(value, dict):
            raise ObservationError(f"{path} must be an object")
        for key, item in value.items():
            check_fields(key, str, f"{path} key")
            check_fields(item, spec[str], f"{path}.{key}")
    elif isinstance(spec, Mapping):
        optional = AFTER_CONTACT if spec is FIELDS else frozenset()
        if not isinstance(value, dict) or not set(spec) - optional <= set(value) <= set(spec):
            got = sorted(value) if isinstance(value, dict) else type(value).__name__
            raise ObservationError(f"{path} keys {got} are not {sorted(spec)}")
        for key, item in value.items():
            check_fields(item, spec[key], f"{path}.{key}")
    elif spec is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ObservationError(f"{path} must be an int")
    elif not isinstance(value, spec):
        raise ObservationError(f"{path} must be {spec.__name__}")


def relative(state: dict, civ_id: str, tile: str) -> str:
    if not tile:
        return ""
    ox, oy = parse_tile_key(state["civs"][civ_id]["origin"])
    x, y = parse_tile_key(tile)
    return tile_key(x - ox, y - oy)


def civ_name(config: Config, civ_id: str) -> str:
    return config.civ(civ_id).name


def _detail(config: Config, state: dict, civ_id: str, detail: str) -> str | None:
    """Event text as the civ may read it: tiles made relative, its own ids kept, a met civ's
    ids replaced by that civ's name. None if the text names a civ it hasn't met. Punctuation
    around a word, as in "(ironhold-u3)", is set aside before matching and put back after."""
    words = []
    for raw in detail.split(" "):
        core = raw.strip(_PUNCTUATION)
        before, after = raw[:raw.index(core)] if core else raw, raw[raw.index(core) + len(core):] if core else ""
        lowered = core.lower()
        owner = next((c for c in state["civs"] if lowered == c or lowered.startswith(c + "-")), None)
        if _TILE.match(core):
            core = relative(state, civ_id, core)
        elif owner and owner != civ_id:
            if owner not in state["civs"][civ_id]["met"]:
                return None
            core = civ_name(config, owner)
        words.append(before + core + after)
    return " ".join(words)


def _trigger(config: Config, state: dict, civ_id: str, raised: dict) -> dict | None:
    """A trigger as the civ sees it, or None if its detail names a civ it hasn't met: the trigger's
    name alone (foreign_unit_sighted, say) would tell it others exist."""
    detail = _detail(config, state, civ_id, raised["detail"])
    if detail is None:
        return None
    return {"trigger": str(raised["trigger"]), "detail": detail}


def _events(config: Config, state: dict, civ_id: str) -> list[dict]:
    """Own and world events since this civ's last turn."""
    seen = []
    for event in state["events"][state["civs"][civ_id]["turn"]["cursor"]:]:
        if event["civ"] not in (civ_id, "world"):
            continue
        detail = _detail(config, state, civ_id, event["detail"])
        if detail is not None:
            seen.append({"tick": event["tick"], "kind": event["kind"], "detail": detail})
    return seen


def observe(config: Config, state: dict, civ_id: str, raised: list[dict] | None = None) -> dict:
    """What civ_id may see now. Pure: tests, the turn step and the inspector all call it."""
    civ = state["civs"][civ_id]
    now = state["tick"]
    own = sorted(sid for sid, s in state["settlements"].items() if s["civ"] == civ_id)
    met = civ["met"]
    world_map = state["map"]
    worked = {b["tile"] for sid in own for b in state["settlements"][sid]["buildings"]}
    known = {}
    for tile in sight.known_tiles(state, civ_id):
        x, y = parse_tile_key(tile)
        known[relative(state, civ_id, tile)] = world_map["biome"][y][x]
    seen_stocks = civ["turn"]["seen_stocks"]
    journal, strategy = memory.view(state, civ_id)
    observation = {
        "tick": now,
        "season": rules.season(now),
        "triggers": [seen for r in (raised or []) if (seen := _trigger(config, state, civ_id, r))],
        "rejections": [dict(r) for r in civ["turn"]["rejections"]],
        "stocks": dict(civ["stocks"]),
        "stock_changes": {res: amount - seen_stocks.get(res, amount) for res, amount in civ["stocks"].items()},
        "population": sum(state["settlements"][sid]["pop"] for sid in own),
        "score": civ["score"],
        "stability": civ["stability"],
        "techs": list(civ["techs"]),
        "allocation": dict(civ["allocation"]),
        "reorders": [dict(r) for r in civ["reorders"]],
        "research": {"tech": civ["research"]["tech"], "points": floor_div(civ["research"]["points_milli"], PER_MILLE),
                     "available": techs.offered(state, civ_id)},
        "build_queue": [{"settlement": e["settlement"], "building": e["building"], "mode": e["mode"],
                         "tile": relative(state, civ_id, e["tile"]), "started": e["started"],
                         "ticks_left": e["ticks_left"]} for e in civ["build_queue"]],
        "settlements": [{"id": sid, "name": state["settlements"][sid]["name"],
                         "tile": relative(state, civ_id, state["settlements"][sid]["tile"]),
                         "stage": state["settlements"][sid]["stage"], "pop": state["settlements"][sid]["pop"],
                         "buildings": [b["type"] for b in state["settlements"][sid]["buildings"]]} for sid in own],
        "units": [{"id": uid, "kind": state["units"][uid]["kind"], "pop": state["units"][uid]["pop"],
                   "tile": relative(state, civ_id, state["units"][uid]["tile"]),
                   "ready": units.is_ready(state, state["units"][uid]),
                   "target": relative(state, civ_id, state["units"][uid]["target"])}
                  for uid in units.of_civ(state, civ_id)],
        "known": known,
        "known_elsewhere": {},
        "nodes": [{"id": node_id, "kind": node["kind"], "tile": relative(state, civ_id, node["tile"]),
                   "settlement": state["territory"][node["tile"]], "left": node["node"] if node["finite"] else -1,
                   "worked": node["tile"] in worked}
                  for node_id, node in sorted(state["nodes"].items())
                  if state["territory"].get(node["tile"]) in own],
        "in_view": [{"civ": civ_name(config, state["units"][uid]["civ"]), "kind": state["units"][uid]["kind"],
                     "tile": relative(state, civ_id, state["units"][uid]["tile"])}
                    for uid in civ["in_view"] if uid in state["units"] and state["units"][uid]["civ"] in met],
        "foreign_sites": [{"civ": civ_name(config, state["settlements"][sid]["civ"]),
                           "tile": relative(state, civ_id, site["tile"])}
                          for sid, site in sorted(civ["sites"].items()) if state["settlements"][sid]["civ"] in met],
        "met": [{"name": civ_name(config, other), "standing": reputation.word(state["reputation"][civ_id][other])}
                for other in sorted(met)],
        "events": _events(config, state, civ_id),
        "journal": [{**e, "about": civ_name(config, e["about"]) if e["about"] else ""} for e in journal],
        "messages": [{"from": civ_name(config, m["from"]), "sent": m["sent"], "hearsay": m["hearsay"], "text": m["text"]}
                     for m in civ["inbox"]],
        "strategy": strategy,
        "elided": [],
    }
    if not met:
        for key in AFTER_CONTACT:
            del observation[key]
    _fit(observation)
    check_fields(observation)
    return observation


def size(observation: dict) -> int:
    return len(canonical_json(observation))


def _fit(observation: dict) -> None:
    """Trim to MAX_CHARS: known tiles more than NEAR from any own settlement or unit become counts
    per biome, then the oldest journal entries go, then the oldest events, then the farthest
    remaining known tiles, then the oldest rejections, until it fits."""
    if size(observation) <= MAX_CHARS:
        return
    anchors = [parse_tile_key(item["tile"]) for item in observation["settlements"] + observation["units"]]

    def reach(tile: str) -> int:
        x, y = parse_tile_key(tile)
        return min((max(abs(x - ax), abs(y - ay)) for ax, ay in anchors), default=0)

    counts: dict[str, int] = {}

    def fold(tiles: list[str]) -> None:
        for tile in tiles:
            code = observation["known"].pop(tile)
            counts[code] = counts.get(code, 0) + 1
        observation["known_elsewhere"] = dict(sorted(counts.items()))

    fold([tile for tile in observation["known"] if reach(tile) > NEAR])
    budget = MAX_CHARS - 240  # room for the elided notes added at the end
    forgotten = 0
    while size(observation) > budget and observation["journal"]:
        observation["journal"].pop(0)
        forgotten += 1
    dropped = 0
    while size(observation) > budget and observation["events"]:
        observation["events"].pop(0)
        dropped += 1
    by_reach = sorted(observation["known"], key=lambda tile: (reach(tile), tile))
    while size(observation) > budget and by_reach:
        over = size(observation) - budget
        fold([by_reach.pop() for _ in range(min(len(by_reach), over // 10 + 1))])  # an entry is about 12 chars
    if counts:
        observation["elided"].append(f"{sum(counts.values())} distant known tiles shown as counts by biome")
    unread = 0
    while size(observation) > budget and observation.get("messages"):
        observation["messages"].pop(0)
        unread += 1
    if unread:
        observation["elided"].append(f"{unread} oldest messages")
    cut = 0
    while size(observation) > budget and observation["rejections"]:
        observation["rejections"].pop(0)
        cut += 1
    if forgotten:
        observation["elided"].append(f"{forgotten} oldest journal entries")
    if cut:
        observation["elided"].append(f"{cut} oldest rejections")
    if dropped:
        observation["elided"].append(f"{dropped} oldest events")
