"""Ruler actions, each checked before it touches state (docs/rules.md section 16).

Each function returns None when the action is accepted and applied, or a short reason code
when it is rejected; a rejected action changes nothing. M4 has set_research and build; the
rest of the action list arrives with standing orders in M5.
"""

from fogline import construction, techs
from fogline.config import Config
from fogline.state import parse_tile_key


def set_research(config: Config, state: dict, civ_id: str, tech_id: str) -> str | None:
    civ = state["civs"].get(civ_id)
    if civ is None:
        return "unknown_civ"
    if tech_id not in techs.TECHS:
        return "unknown_tech"
    if tech_id in civ["techs"]:
        return "already_known"
    if not techs.prereqs_met(civ["techs"], tech_id):
        return "prereqs_missing"
    if not techs.gate_met(state, civ_id, techs.TECHS[tech_id].gate):
        return "gate_unmet"
    civ["research"]["tech"] = tech_id
    return None


def _entry(config: Config, settlement_id: str, building: str, mode: str, hint: str, tile: str) -> dict:
    return {"settlement": settlement_id, "building": building, "mode": mode, "hint": hint, "tile": tile,
            "cost": construction.queue_cost(config, building, mode),
            "ticks_left": construction.queue_ticks(config, building, mode), "started": False, "dropped": False}


def build(config: Config, state: dict, civ_id: str, settlement_id: str, building: str,
          tile: str | None = None) -> str | None:
    """Queue a building. A tile holding one of the civ's own ruined or damaged buildings of the same
    type queues a rebuild or a repair; any other tile is a hint for a new building."""
    civ = state["civs"].get(civ_id)
    if civ is None:
        return "unknown_civ"
    if building not in config.buildings:
        return "unknown_building"
    settlement = state["settlements"].get(settlement_id)
    if settlement is None or settlement["civ"] != civ_id:
        return "not_own_settlement"
    if config.buildings[building]["tech"] not in civ["techs"]:
        return "tech_missing"
    if len(civ["build_queue"]) >= config.build_queue_max:
        return "queue_full"
    if tile is not None:
        try:
            parse_tile_key(tile)
        except ValueError:
            return "bad_tile"
        for sid in sorted(sid for sid, s in state["settlements"].items() if s["civ"] == civ_id):
            for existing in state["settlements"][sid]["buildings"]:
                if existing["tile"] != tile:
                    continue
                if existing["type"] != building or not (existing["ruin"] or existing["damaged"]):
                    return "tile_taken"
                if any(e["tile"] == tile for e in civ["build_queue"]):
                    return "already_queued"
                mode = "rebuild" if existing["ruin"] else "repair"
                civ["build_queue"].append(_entry(config, sid, building, mode, "", tile))
                return None
    placed = construction.place(config, state, settlement_id, building, tile)
    if placed is None:
        return "no_tile"
    civ["build_queue"].append(_entry(config, placed[1], building, "new", tile or "", ""))
    return None
