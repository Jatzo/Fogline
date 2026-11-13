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
                400, 450, 600, {"food": 1500, "timber": 250, "stone": 300, "metal": 200, "luxury": 0}),
        CivSpec("verdance", "Verdance", "forest", ("food", "timber"), ("metal",), "dye",
                800, 150, 200, {"food": 400, "timber": 300, "stone": 200, "metal": 110, "luxury": 0}),
        CivSpec("saltreach", "Saltreach", "coast", ("food", "stone"), ("timber",), "pearls",
                500, 400, 250, {"food": 400, "timber": 600, "stone": 250, "metal": 150, "luxury": 0}),
        CivSpec("dunerunners", "Dunerunners", "desert", ("metal", "stone"), ("food", "timber"), "spice",
                250, 800, 400, {"food": 2000, "timber": 650, "stone": 250, "metal": 200, "luxury": 0}),
        CivSpec("frostmark", "Frostmark", "tundra", ("timber", "metal"), ("stone",), "amber",
                450, 350, 800, {"food": 400, "timber": 300, "stone": 220, "metal": 150, "luxury": 0}),
    )


@dataclass(frozen=True)
class Config:
    # Map and worldgen (rules 2)
    map_size: int = 76  # 64 tiles of land inside a sea border
    sea_border: int = 6  # the largest sight (fortress, 4) plus the order margin (2): nobody sees or probes the edge
    edge_margin: int = 4
    slice_pair: tuple[str, ...] = ()  # the Phase 3b slice: these two start as neighbours and meet at once
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
    # Per-mille bonus by work line: crop rotation on farms, quarrying on stone, iron working on metal.
    tech_bonus: dict[str, tuple[str, int]] = field(default_factory=lambda: {
        "crop_rotation": ("farm", 250), "quarrying": ("stone", 250), "iron_working": ("metal", 250)})
    sawmill_bonus: int = 300
    impaired_rate: int = 500  # a damaged building, or one with upkeep in arrears, runs at half output
    # Worker allocation by line, in percent, until a ruler sets one (standing orders arrive in M5).
    default_allocation: dict[str, int] = field(default_factory=lambda: {
        "food": 50, "timber": 15, "stone": 10, "metal": 10, "luxury": 5, "research": 10})

    # Population and consumption (rules 4)
    housing_capacity: int = 10
    growth_rate: int = 15
    culture_growth_rate: dict[str, int] = field(default_factory=lambda: {"verdance": 20})
    starvation_divisor: int = 4
    food_window_ticks: int = 4
    supply_floor: int = 0  # test-only stand-in for trade (ADR 0004); 0 is off
    growth_store_ticks: int = 40  # a food stock this many ticks of eating deep also lets a civ grow
    food_per_person: int = 1
    spoilage: int = 5
    spoilage_granary: int = 2
    fuel_people_per_unit: int = 10
    fuel_winter_units: int = 2
    building_timber_upkeep: int = 1
    building_stone_upkeep: int = 1
    stone_building_extra_upkeep: int = 2
    stone_buildings: tuple[str, ...] = ("workshop", "granary", "library", "market", "barracks", "town_walls",
                                        "harbour", "stone_fortress", "printing_house")
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

    # Units (rules 6). Caravans arrive with trade in Phase 3. "army" units share the scaled upkeep;
    # "building" is a building the training settlement must have.
    units: dict[str, dict] = field(default_factory=lambda: {
        "scout": {"cost": {"food": 15, "timber": 5}, "pop": 1, "upkeep": 1, "move": 8, "sight": 2,
                  "strength": 0, "tech": "", "building": "", "train_ticks": 1, "army": False},
        "levy": {"cost": {"food": 10, "metal": 5}, "pop": 5, "upkeep": 1, "move": 4, "sight": 2,
                 "strength": 2, "tech": "", "building": "", "train_ticks": 1, "army": True},
        "soldiers": {"cost": {"food": 20, "metal": 10, "timber": 5}, "pop": 5, "upkeep": 2, "move": 4, "sight": 2,
                     "strength": 5, "tech": "drill", "building": "barracks", "train_ticks": 2, "army": True},
        "caravan": {"cost": {"timber": 20, "food": 10}, "pop": 2, "upkeep": 1, "move": 4, "sight": 2,
                    "strength": 0, "tech": "", "building": "", "train_ticks": 1, "army": False},
    })
    scout_move_pathfinding: int = 10
    scout_sight_pathfinding: int = 3
    settlement_sight: int = 2
    fortress_sight: int = 4
    army_upkeep_step: int = 250
    army_upkeep_every: int = 10
    order_margin: int = 2  # a move target must be this close to ground the civ has seen

    # Tech (rules 14)
    tech_speed: int = 1000
    era_points: dict[str, int] = field(default_factory=lambda: {"1": 160, "2": 480, "3": 1200})
    library_scholar_rate: int = 1500
    printing_rate: int = 1500
    catch_up_discount: int = 250
    era_resources: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "1": {"timber": 20}, "2": {"timber": 40, "stone": 20, "metal": 10},
        "3": {"stone": 60, "metal": 30, "luxury": 10}})

    # Score (rules 18)
    score_per_building: int = 5
    score_per_tech: int = 20
    score_luxury_divisor: int = 10

    # Buildings (rules 15.1): cost, build ticks and the tech that unlocks each one.
    buildings: dict[str, dict] = field(default_factory=lambda: {
        "housing": {"cost": {"timber": 10}, "ticks": 1, "tech": "huts"},
        "farm": {"cost": {"timber": 10}, "ticks": 1, "tech": "farming"},
        "lumber_camp": {"cost": {"timber": 5}, "ticks": 1, "tech": "basic_crafts"},
        "mine": {"cost": {"timber": 15}, "ticks": 2, "tech": "simple_tools"},
        "workshop": {"cost": {"timber": 20, "stone": 10}, "ticks": 2, "tech": "basic_crafts"},
        "pasture": {"cost": {"timber": 10}, "ticks": 1, "tech": "herding"},
        "sawmill": {"cost": {"timber": 30, "stone": 10}, "ticks": 2, "tech": "woodworking"},
        "granary": {"cost": {"timber": 30, "stone": 20}, "ticks": 2, "tech": "storage"},
        "library": {"cost": {"timber": 40, "stone": 30, "metal": 5}, "ticks": 3, "tech": "writing"},
        "market": {"cost": {"timber": 40, "stone": 20}, "ticks": 3, "tech": "markets"},
        "barracks": {"cost": {"timber": 40, "stone": 30, "metal": 10}, "ticks": 3, "tech": "drill"},
        "town_walls": {"cost": {"stone": 80}, "ticks": 4, "tech": "masonry"},
        "harbour": {"cost": {"timber": 50, "stone": 30}, "ticks": 4, "tech": "harbours"},
        "stone_fortress": {"cost": {"stone": 200, "metal": 40, "luxury": 20}, "ticks": 8, "tech": "fortification"},
        "printing_house": {"cost": {"timber": 60, "stone": 60, "metal": 20, "luxury": 20}, "ticks": 6,
                           "tech": "printing"},
    })
    build_queue_max: int = 5
    rebuild_rate: int = 500
    repair_rate: int = 250
    repair_ticks: int = 1
    pasture_biomes: tuple[str, ...] = ("plains", "tundra", "desert")

    # Settlements (rules 15)
    stage_order: tuple[str, ...] = ("hamlet", "village", "town", "city")
    stage_min_pop: dict[str, int] = field(default_factory=lambda: {
        "hamlet": 0, "village": 25, "town": 60, "city": 150})
    stage_min_buildings: dict[str, int] = field(default_factory=lambda: {
        "hamlet": 0, "village": 4, "town": 8, "city": 14})
    stage_requires: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "town": ("market", "library"), "city": ("town_walls",)})
    stage_drop_ticks: int = 4
    node_claim_reach: int = 3
    node_claim_radius: int = 1
    claim_extra_radius: int = 3
    track_passes: int = 6

    # Runs
    snapshot_every: int = 4  # one snapshot a year

    # Wake rules (rules 16)
    heartbeat_ticks: int = 6
    max_wake_ticks: int = 8
    max_reorders: int = 3
    max_actions_per_turn: int = 12
    invalid_turns_before_skip: int = 3
    max_concurrent_calls: int = 5  # rulers called at once in a tick (rules 16)

    # Messages and couriers (rules 7)
    message_chars: int = 600  # after hardening
    message_raw_chars: int = 2000  # what an order may carry before hardening
    messages_per_contact: int = 2  # per tick
    courier_pace: int = 8  # movement points a tick
    inbox_size: int = 8
    quote_chars: int = 80  # a foreign claim kept in memory, and the most a note may share with a message

    # Trade (rules 8; Phase 3 readings in rules 21)
    caravan_capacity: int = 100  # goods one caravan carries; Carts doubles it
    base_value: dict[str, int] = field(default_factory=lambda: {
        "food": 1, "timber": 2, "stone": 2, "metal": 4, "luxury": 8})
    blueprint_value_per_era: int = 100
    market_fee: int = 100  # per mille of each good received, without a market
    market_fee_with_market: int = 50
    culture_market_fee: dict[str, int] = field(default_factory=lambda: {"saltreach": 20})
    fee_halving_view: int = 30
    fair_trade_margin: int = 250  # per mille: within 25% of base value
    max_offer_goods: int = 6
    max_offer_ticks: int = 8

    # Reputation (rules 11)
    reputation_drift_every: int = 4

    # Memory (PLAN section 8)
    journal_entries: int = 16
    journal_chars: int = 200
    strategy_chars: int = 800
    reflect_every: int = 8  # ticks between reflections (two in-world years)

    # Providence (rules 19)
    events_enabled: bool = True
    world_event_chance: int = 20
    quirk_event_chance: int = 20
    drought_rate: int = 600
    drought_ticks: int = 4
    plague_loss: int = 100
    plague_stability: int = 10
    harsh_winter_fuel: int = 2000
    comet_stability: int = 5
    comet_ticks: int = 2
    discovery_node_size: int = 1500
    flood_rate: int = 500
    flood_ticks: int = 2
    quirk_line_rate: int = 100
    quirk_ticks: int = 2
    quirk_stability: int = 3
    # What each town quirk does when it fires: a line +/-10% for 2 ticks, or stability +/-3.
    quirk_effects: dict[str, tuple[str, int]] = field(default_factory=lambda: {
        "famed_smith": ("metal", 1), "fragile_harbour": ("food", -1), "plague_prone_slum": ("stability", -1),
        "lucky_harvests": ("food", 1), "quarrelsome_guilds": ("stability", -1), "old_shrine": ("stability", 1),
        "rich_seam": ("stone", 1), "flood_meadow": ("food", -1), "proud_militia": ("stability", 1),
        "busy_crossroads": ("timber", 1), "lean_winters": ("food", -1), "storytellers": ("research", 1)})

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
