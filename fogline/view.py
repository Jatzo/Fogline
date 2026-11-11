"""What the viewer is sent (PLAN section 12, Phase 1: the read-only map).

Plain functions over a state dict. They copy what the map needs and never change the state;
the viewer tests hold that with the state hash.
"""

from fogline.config import Config
from fogline.state import parse_tile_key
from fogline.techs import TECHS

SETTLEMENT_FIELDS = ("civ", "name", "tile", "stage", "pop", "capital", "specialty", "need", "quirk")


def world(config: Config, state: dict) -> dict:
    """The parts that never change during a run: the map and the civs. Sent once."""
    world_map = state["map"]
    return {
        "size": world_map["size"],
        "techs": len(TECHS),
        "biome": list(world_map["biome"]),
        "river": list(world_map["river"]),
        "civs": [{"id": civ_id, "name": config.civ(civ_id).name, "home": config.civ(civ_id).home_biome}
                 for civ_id in sorted(state["civs"])],
    }


def frame(state: dict) -> dict:
    """One moment of a run. Territory is a grid of indexes into this frame's settlement list
    (-1 for unclaimed), so the client must read the list again for every frame."""
    ids = sorted(state["settlements"])
    index = {sid: i for i, sid in enumerate(ids)}
    size = state["map"]["size"]
    territory = [[-1] * size for _ in range(size)]
    for tile, owner in state["territory"].items():
        x, y = parse_tile_key(tile)
        territory[y][x] = index[owner]
    settlements, buildings = [], []
    for sid in ids:
        town = state["settlements"][sid]
        settlements.append({"id": sid, **{key: town[key] for key in SETTLEMENT_FIELDS}})
        buildings.extend({"town": index[sid], "type": b["type"], "tile": b["tile"],
                          "ruin": b["ruin"], "damaged": b["damaged"]} for b in town["buildings"])
    return {
        "tick": state["tick"],
        "settlements": settlements,
        "territory": territory,
        "buildings": buildings,
        "nodes": [{"kind": n["kind"], "tile": n["tile"], "left": n["node"], "size": n["size"]}
                  for _, n in sorted(state["nodes"].items())],
        "units": [{"civ": u["civ"], "kind": u["kind"], "tile": u["tile"]}
                  for _, u in sorted(state["units"].items())],
        "civs": {civ_id: {"techs": len(civ["techs"]), "stability": civ["stability"]}
                 for civ_id, civ in sorted(state["civs"].items())},
    }
