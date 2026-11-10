"""Every number in docs/rules.md, as one frozen config.

The engine reads numbers only from here, so tuning a rule means changing one value and
the config hash recorded with each run. Rates are per mille (1000 = 100%).
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from fogline.state import state_hash

RESOURCES = ("food", "timber", "stone", "metal", "luxury")
BASICS = ("food", "timber", "stone", "metal")
SEASONS = ("spring", "summer", "autumn", "winter")


@dataclass(frozen=True)
class CivSpec:
    civ_id: str
    name: str
    home_biome: str
    rich_in: tuple[str, ...]
    short_of: tuple[str, ...]
    luxury: str
    generosity: int
    ruthlessness: int
    insularity: int
    start_stock: Mapping[str, int]

    def __post_init__(self) -> None:
        # Read-only, so worldgen can't hand the engine a dict that would change the config.
        object.__setattr__(self, "start_stock", MappingProxyType(dict(self.start_stock)))


def _civs() -> tuple[CivSpec, ...]:
    return (
        CivSpec("ironhold", "Ironhold", "mountains", ("stone", "metal"), ("food",), "gemstones",
                400, 450, 600, {"food": 1200, "timber": 250, "stone": 300, "metal": 200, "luxury": 0}),
        CivSpec("verdance", "Verdance", "forest", ("food", "timber"), ("metal",), "dye",
                800, 150, 200, {"food": 400, "timber": 300, "stone": 200, "metal": 60, "luxury": 0}),
        CivSpec("saltreach", "Saltreach", "coast", ("food", "stone"), ("timber",), "pearls",
                500, 400, 250, {"food": 400, "timber": 150, "stone": 250, "metal": 150, "luxury": 0}),
        CivSpec("dunerunners", "Dunerunners", "desert", ("metal", "stone"), ("food", "timber"), "spice",
                250, 800, 400, {"food": 1200, "timber": 150, "stone": 250, "metal": 200, "luxury": 0}),
        CivSpec("frostmark", "Frostmark", "tundra", ("timber", "metal"), ("stone",), "amber",
                450, 350, 800, {"food": 400, "timber": 300, "stone": 120, "metal": 150, "luxury": 0}),
    )


@dataclass(frozen=True)
class Config:
    # Map and worldgen (rules 2)
    map_size: int = 64
    edge_margin: int = 4
    min_capital_path_cost: int = 40
    capital_ring_radius: int = 24  # capitals sit on a pentagon this far from the map centre
    capital_jitter: int = 2
    worldgen_attempts: int = 20
    home_radius: int = 10
    home_node_ring_min: int = 2
    home_node_ring_max: int = 5
    capital_farmland_min: int = 8
    outpost_min_spacing: int = 4
    contestable_min_spacing: int = 6
    noise_spacing: int = 8
    outposts_per_civ: int = 3
    # Outposts sit just outside the capital's starting claim (village radius 2 + 3), so they own land.
    outpost_distance_min: int = 7
    outpost_distance_max: int = 9
    move_cost: dict[str, int] = field(default_factory=lambda: {
        "plains": 1, "coast": 1, "forest": 2, "desert": 2, "tundra": 2, "mountains": 3})
    river_crossing_cost: int = 1
    forest_node_size: int = 2000
    forest_regrowth: int = 10
    stone_node_size: int = 3000
    metal_node_size: int = 2000
    short_food_worker_cap: int = 12
    short_forest_size: int = 500
    short_forest_regrowth: int = 2
    short_stone_size: int = 300
    short_metal_size: int = 250
    contestable_nodes_min: int = 3
    contestable_nodes_max: int = 5
    contestable_cost_gap: int = 6
    luxury_workers_max: int = 2

    # Production (rules 3)
    output_per_worker: dict[str, int] = field(default_factory=lambda: {
        "farm": 3, "pasture": 2, "fishing": 3, "timber": 2, "stone": 2, "metal": 1, "luxury": 1, "research": 1})
    slots: dict[str, int] = field(default_factory=lambda: {
        "farm": 5, "pasture": 4, "fishing_no_harbour": 2, "fishing_harbour": 6, "lumber_camp": 5,
        "mine": 4, "workshop": 4, "library": 6})
    food_season: dict[str, int] = field(default_factory=lambda: {
        "spring": 1000, "summer": 1250, "autumn": 1500, "winter": 250})
    fishing_season: dict[str, int] = field(default_factory=lambda: {
        "spring": 1000, "summer": 1000, "autumn": 1000, "winter": 750})
    specialty_bonus: int = 400
    specialty_penalty: int = 300
    diminishing_step: int = 100
    diminishing_floor: int = 500

    # Population and consumption (rules 4)
    housing_capacity: int = 10
    growth_rate: int = 15
    food_per_person: int = 1
    spoilage: int = 5
    spoilage_granary: int = 2
    fuel_people_per_unit: int = 10
    fuel_winter_units: int = 3
    building_timber_upkeep: int = 1
    building_stone_upkeep: int = 1
    stone_building_extra_upkeep: int = 2
    cold_death_rate: int = 20
    tool_wear_workers: int = 25
    tool_shortage_penalty: int = 200
    ruin_after_ticks: int = 8
    luxury_use_every: int = 4
    starting_capital_pop: int = 40
    starting_outpost_pop: int = 5

    # Stability (rules 5)
    stability_start: int = 60
    stability_base: int = 50
    stability_step: int = 5
    stability_fed: int = 10
    stability_luxury: int = 5
    stability_comfort_each: int = 5
    stability_comfort_max: int = 15
    stability_aid_per: int = 50
    stability_aid_max: int = 5
    stability_unfed_per_10pct: int = 2
    stability_no_fuel: int = 10
    stability_arrears: int = 5
    stability_captured: int = 10
    stability_raid: int = 3
    stability_combat: int = 2
    stability_output_base: int = 800
    stability_output_per_point: int = 4
    unrest_below: int = 25
    unrest_chance: int = 100
    riot_stock_loss: int = 50
    secession_below: int = 10
    secession_ticks: int = 4
    secession_idle_ticks: int = 4

    # Units (rules 6)
    scout_move: int = 4
    scout_move_pathfinding: int = 6
    scout_sight: int = 2
    scout_sight_pathfinding: int = 3
    unit_sight: int = 2
    settlement_sight: int = 2
    fortress_sight: int = 4
    army_upkeep_step: int = 250

    # Tech (rules 14)
    tech_speed: int = 1000
    era_points: dict[str, int] = field(default_factory=lambda: {"1": 80, "2": 240, "3": 600})
    library_scholar_rate: int = 1500
    printing_rate: int = 1500
    catch_up_discount: int = 250
    tech_options_shown: int = 3

    # Settlements (rules 15)
    claim_extra_radius: int = 3
    track_passes: int = 6

    # Wake rules (rules 16)
    heartbeat_ticks: int = 6
    max_actions_per_turn: int = 12
    invalid_turns_before_skip: int = 3

    # Providence (rules 19)
    events_enabled: bool = True
    world_event_chance: int = 20
    quirk_event_chance: int = 20

    civs: tuple[CivSpec, ...] = field(default_factory=_civs)

    def civ(self, civ_id: str) -> CivSpec:
        for spec in self.civs:
            if spec.civ_id == civ_id:
                return spec
        raise KeyError(civ_id)

    def to_plain(self) -> dict[str, Any]:
        """Plain data for hashing and for the run manifest (tuples become lists)."""
        plain = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        plain["civs"] = [{f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)} for spec in self.civs]
        return _plain(plain)

    def config_hash(self) -> str:
        return state_hash(self.to_plain())


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
