"""Fog tests for the observation builder (PLAN sections 7 and 14, ADR 0006).

Every observation is checked at the moment a decider receives it, against the live state, over
ten seeds of spiral scouts so the known map spreads and civs meet. The metamorphic test changes
ground truth a civ can't see and requires its observation to stay byte-identical.
"""

import copy
import json

import pytest

from fogline import bots, engine, observation, sight, worldgen
from fogline.config import Config
from fogline.state import canonical_json, parse_tile_key, tile_key

CONFIG = Config()
SEEDS = range(1, 11)
TICKS = 150
PROBE_TICKS = (16, 64, 128)  # where the metamorphic test reruns observe() on a changed copy


def _absolute(state, civ_id, tile):
    ox, oy = parse_tile_key(state["civs"][civ_id]["origin"])
    x, y = parse_tile_key(tile)
    return x + ox, y + oy


def _foreign_words(state, civ_id):
    """Every id and name of the civs civ_id hasn't met, lower-cased."""
    met = set(state["civs"][civ_id]["met"])
    words = set()
    for other in state["civs"]:
        if other != civ_id and other not in met:
            words |= {other.lower(), CONFIG.civ(other).name.lower()}
    return words


def _hide_the_unseen(state, civ_id):
    """A copy of state that differs only in things civ_id has not seen."""
    changed = copy.deepcopy(state)
    met = set(state["civs"][civ_id]["met"])
    for other, civ in changed["civs"].items():
        if other == civ_id or other in met:
            continue
        civ["stocks"] = {res: amount + 37 for res, amount in civ["stocks"].items()}
        civ["stability"] = (civ["stability"] + 11) % 100
        civ["techs"] = sorted(set(civ["techs"]) | {"writing"})
    for settlement in changed["settlements"].values():
        if settlement["civ"] != civ_id and settlement["civ"] not in met:
            settlement["pop"] += 5
    for unit in changed["units"].values():
        if unit["civ"] != civ_id and unit["civ"] not in met:
            unit["pop"] += 1
    own_land = {t for t, sid in state["territory"].items() if state["settlements"][sid]["civ"] == civ_id}
    rows = [list(row) for row in changed["map"]["biome"]]
    for y, row in enumerate(rows):
        for x, code in enumerate(row):
            if not sight.is_known(state, civ_id, x, y) and tile_key(x, y) not in own_land and code != "S":
                row[x] = "M" if code != "M" else "P"
    changed["map"]["biome"] = ["".join(row) for row in rows]
    return changed


@pytest.fixture(scope="module")
def checked():
    """Play every seed, checking each observation as it is handed over. Returns counts."""
    counts = {"observations": 0, "met": 0, "probes": 0, "tiles": 0}
    for seed in SEEDS:
        state = worldgen.generate(CONFIG, seed)

        def watch(civ_id):
            def decide(seen, scratch):
                _check(state, civ_id, seen, counts)
                return bots.spiral_scout(seen, scratch)
            return decide

        engine.run(CONFIG, state, TICKS, deciders={civ: watch(civ) for civ in state["civs"]})
    return counts


def _check(state, civ_id, seen, counts):
    counts["observations"] += 1
    counts["met"] += bool(seen.get("met"))
    assert ("met" in seen) == bool(state["civs"][civ_id]["met"])  # no hint of others before contact
    observation.check_fields(seen)
    assert observation.size(seen) <= observation.MAX_CHARS

    for tile in seen["known"]:
        x, y = _absolute(state, civ_id, tile)
        assert sight.is_known(state, civ_id, x, y), (civ_id, tile)
        counts["tiles"] += 1
    for item in seen.get("in_view", []) + seen.get("foreign_sites", []):
        assert sight.is_known(state, civ_id, *_absolute(state, civ_id, item["tile"]))

    text = json.dumps(seen).lower()
    for word in _foreign_words(state, civ_id):
        assert word not in text, (civ_id, word, seen["tick"])
    assert str(state["map"]["size"]) not in json.dumps(seen["known"])  # no absolute tile leaks the size

    if seen["tick"] in PROBE_TICKS:
        counts["probes"] += 1
        # The live observation also moved the event cursor's view; rebuild both from the same point.
        plain = observation.observe(CONFIG, state, civ_id)
        changed = observation.observe(CONFIG, _hide_the_unseen(state, civ_id), civ_id)
        assert canonical_json(changed) == canonical_json(plain), (civ_id, seen["tick"])


def test_every_observation_holds_only_whitelisted_seen_and_met_things(checked):
    # Enough ground covered that the checks mean something.
    assert checked["observations"] > 1_000
    assert checked["tiles"] > 100_000
    assert checked["met"] > 0, "no civ met another, so the after-contact path went untested"


def test_changing_what_a_civ_cannot_see_leaves_its_observation_unchanged(checked):
    assert checked["probes"] >= len(SEEDS) * len(PROBE_TICKS)


def test_an_unknown_key_is_refused():
    state = worldgen.generate(CONFIG, 1)
    seen = observation.observe(CONFIG, state, "verdance")
    seen["map_size"] = state["map"]["size"]
    with pytest.raises(observation.ObservationError):
        observation.check_fields(seen)
    del seen["map_size"]
    seen["units"][0]["civ_count"] = 5
    with pytest.raises(observation.ObservationError):
        observation.check_fields(seen)


def test_event_text_is_made_relative_and_unmet_civs_are_dropped():
    state = worldgen.generate(CONFIG, 1)
    ox, oy = parse_tile_key(state["civs"]["verdance"]["origin"])
    turn = state["civs"]["verdance"]["turn"]
    turn["cursor"] = len(state["events"])
    state["events"] += [
        {"tick": 0, "kind": "built", "civ": "verdance", "detail": f"new farm at {ox + 3},{oy - 2}"},
        {"tick": 0, "kind": "sighted", "civ": "verdance", "detail": "ironhold-u0"},
        {"tick": 0, "kind": "plague", "civ": "ironhold", "detail": "ironhold-0"},
        {"tick": 0, "kind": "comet", "civ": "world", "detail": ""},
    ]
    events = observation.observe(CONFIG, state, "verdance")["events"]
    assert events == [{"tick": 0, "kind": "built", "detail": "new farm at 3,-2"},
                      {"tick": 0, "kind": "comet", "detail": ""}]

    state["civs"]["verdance"]["met"] = {"ironhold": 0} if isinstance(state["civs"]["verdance"]["met"], dict) \
        else ["ironhold"]
    sighted = [e for e in observation.observe(CONFIG, state, "verdance")["events"] if e["kind"] == "sighted"]
    assert sighted == [{"tick": 0, "kind": "sighted", "detail": CONFIG.civ("ironhold").name}]


def test_a_crowded_observation_is_trimmed_to_the_cap_and_says_what_went():
    state = worldgen.generate(CONFIG, 1)
    civ = state["civs"]["verdance"]
    civ["known"] = ["1" * state["map"]["size"] for _ in range(state["map"]["size"])]  # everything seen
    civ["turn"]["cursor"] = len(state["events"])
    state["events"] += [{"tick": 0, "kind": "tech", "civ": "verdance", "detail": f"filler {n}"} for n in range(400)]
    seen = observation.observe(CONFIG, state, "verdance")
    assert observation.size(seen) <= observation.MAX_CHARS
    assert seen["known_elsewhere"] and seen["elided"]
    assert len(seen["known"]) < state["map"]["size"] ** 2
