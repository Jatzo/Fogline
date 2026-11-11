"""The v1 tech tree as data (docs/rules.md section 14, PLAN section 3b).

Four starting techs plus seventeen to unlock. Gates are geography the civ must hold in its
own territory. What each tech does lives where it acts: production bonuses in config.tech_bonus,
unlocked buildings in config.buildings.
"""

from dataclasses import dataclass

from fogline.config import Config
from fogline.intmath import PER_MILLE, per_mille
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


# What a ruler is told about a tech it could study next (rules 14): in-fiction, one line each.
HINTS: dict[str, str] = {
    "crop_rotation": "Resting a field one year in three keeps it from tiring.",
    "herding": "Animals kept on open grass feed people where crops won't grow.",
    "woodworking": "Better joints and tools get more from every felled tree.",
    "quarrying": "Stone cut from a hillside, not just gathered from the ground.",
    "storage": "Sealed granaries that keep a good harvest from rotting.",
    "pathfinding": "Scouts who read the land travel further and see more.",
    "writing": "Marks that keep what scholars learn after they are gone.",
    "iron_working": "Ore from the ground turned into tools that last.",
    "roads": "Packed ways between settlements that speed every journey.",
    "carts": "Wheels that let one caravan carry twice the load.",
    "masonry": "Cut stone laid true, for buildings that outlast their builders.",
    "markets": "A fixed place and fixed rules for exchanging goods.",
    "drill": "People trained to stand and move together.",
    "irrigation": "Water led from the river to fields that would otherwise be dry.",
    "harbours": "Sheltered water where boats can tie up and fish come in.",
    "fortification": "Walls and towers that make a settlement hard to take.",
    "printing": "Words set once and copied many times.",
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


def offered(state: dict, civ_id: str) -> list[dict]:
    """Every tech a ruler could study now, in tree order, with a hint (rules 21 drops the cap of 3).
    available() already leaves out any tech whose gate the civ's own land doesn't meet, so a tech
    needing terrain or a node the civ has never seen is never offered."""
    return [{"tech": t, "hint": HINTS[t]} for t in available(state, civ_id)]


def points(config: Config, state: dict, civ_id: str, tech_id: str) -> int:
    """Research points for one tech, 25% fewer if a civ this one has met already holds it."""
    full, _ = cost(config, tech_id)
    if any(tech_id in state["civs"][other]["techs"] for other in state["civs"][civ_id]["met"]):
        return per_mille(full, PER_MILLE - config.catch_up_discount)
    return full


def cost(config: Config, tech_id: str) -> tuple[int, dict[str, int]]:
    """Research points (scaled by tech_speed) and resources for one tech."""
    era = str(TECHS[tech_id].era)
    return per_mille(config.era_points[era], config.tech_speed), dict(config.era_resources[era])
