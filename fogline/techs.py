"""The v1 tech tree as data (docs/rules.md section 14, PLAN section 3b).

Four starting techs plus seventeen to unlock. Gates are geography the civ must hold in its
own territory. What each tech does lives where it acts: production bonuses in config.tech_bonus,
unlocked buildings in config.buildings.
"""

from dataclasses import dataclass

from fogline.config import Config
from fogline.intmath import per_mille
from fogline.layout import biome_name
from fogline.paths import is_river
from fogline.state import parse_tile_key


@dataclass(frozen=True)
class Tech:
    era: int  # 0 for the starting techs
    needs: tuple[str, ...] = ()
    gate: str = ""  # "", "stone_node", "metal_node", "river" or "coast"


TECHS: dict[str, Tech] = {
    "farming": Tech(0),
    "simple_tools": Tech(0),
    "huts": Tech(0),
    "basic_crafts": Tech(0),
    "crop_rotation": Tech(1, ("farming",)),
    "herding": Tech(1, ("farming",)),
    "woodworking": Tech(1, ("basic_crafts",)),
    "quarrying": Tech(1, ("simple_tools",), "stone_node"),
    "storage": Tech(1, ("farming", "basic_crafts")),
    "pathfinding": Tech(1, ("basic_crafts",)),
    "writing": Tech(1, ("basic_crafts",)),
    "iron_working": Tech(2, ("quarrying",), "metal_node"),
    "roads": Tech(2, ("quarrying", "pathfinding")),
    "carts": Tech(2, ("woodworking",)),
    "masonry": Tech(2, ("quarrying",)),
    "markets": Tech(2, ("writing", "storage")),
    "drill": Tech(2, ("woodworking",)),
    "irrigation": Tech(2, ("crop_rotation",), "river"),
    "harbours": Tech(3, ("woodworking", "masonry"), "coast"),
    "fortification": Tech(3, ("masonry", "iron_working")),
    "printing": Tech(3, ("writing", "markets")),
}


def own_tiles(state: dict, civ_id: str) -> list[str]:
    return sorted(tile for tile, sid in state["territory"].items() if state["settlements"][sid]["civ"] == civ_id)


def gate_met(state: dict, civ_id: str, gate: str) -> bool:
    if not gate:
        return True
    tiles = own_tiles(state, civ_id)
    if gate in ("stone_node", "metal_node"):
        kind = gate.removesuffix("_node")
        held = set(tiles)
        return any(node["kind"] == kind and node["tile"] in held for node in state["nodes"].values())
    if gate == "river":
        return any(is_river(state["map"], *parse_tile_key(tile)) for tile in tiles)
    if gate == "coast":
        return any(biome_name(state["map"], tile) == "coast" for tile in tiles)
    raise ValueError(f"unknown gate {gate!r}")


def prereqs_met(held: list[str], tech_id: str) -> bool:
    return all(need in held for need in TECHS[tech_id].needs)


def available(state: dict, civ_id: str) -> list[str]:
    """Techs the civ lacks whose prerequisites and gate it meets, in tree order."""
    held = state["civs"][civ_id]["techs"]
    return [tech_id for tech_id, tech in TECHS.items()
            if tech_id not in held and prereqs_met(held, tech_id) and gate_met(state, civ_id, tech.gate)]


def cost(config: Config, tech_id: str) -> tuple[int, dict[str, int]]:
    """Research points (scaled by tech_speed) and resources for one tech."""
    era = str(TECHS[tech_id].era)
    return per_mille(config.era_points[era], config.tech_speed), dict(config.era_resources[era])
