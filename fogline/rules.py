"""Pure economy formulas from docs/rules.md sections 3 to 5.

No state and no randomness: each function takes numbers and returns numbers, so every rule
can be checked against a hand-worked case. The engine decides when to call them.
"""

from collections.abc import Iterable, Mapping

from fogline.config import SEASONS, Config
from fogline.intmath import PER_MILLE, ceil_div, floor_div, per_mille

LINES = ("food", "timber", "stone", "metal", "luxury", "research")
# The resource line each kind of work feeds.
WORK_LINE = {"farm": "food", "pasture": "food", "fishing": "food", "timber": "timber", "stone": "stone",
             "metal": "metal", "luxury": "luxury", "research": "research"}


def season(tick: int) -> str:
    return SEASONS[tick % len(SEASONS)]


def diminishing(config: Config, nth: int) -> int:
    """Rate for the nth building of one type in a settlement (nth counts from 1)."""
    return max(PER_MILLE - (nth - 1) * config.diminishing_step, config.diminishing_floor)


def season_rate(config: Config, work: str, season_name: str) -> int:
    if work in ("farm", "pasture"):
        return config.food_season[season_name]
    if work == "fishing":
        return config.fishing_season[season_name]
    return PER_MILLE


def specialty_rate(config: Config, specialty: Mapping[str, str], line: str) -> int:
    if specialty.get("strong") == line:
        return PER_MILLE + config.specialty_bonus
    if specialty.get("weak") == line:
        return PER_MILLE - config.specialty_penalty
    return PER_MILLE


def tech_rate(config: Config, techs: Iterable[str], work: str) -> int:
    held = set(techs)
    bonus = sum(rate for tech, (target, rate) in sorted(config.tech_bonus.items()) if target == work and tech in held)
    return PER_MILLE + bonus


def stability_rate(config: Config, stability: int) -> int:
    """Output multiplier: 800 at stability 0, 1000 at 50, 1200 at 100."""
    return config.stability_output_base + config.stability_output_per_point * stability


def apply_rates(value: int, rates: Iterable[int]) -> int:
    """Apply per-mille rates in order, rounding down after each."""
    for rate in rates:
        value = per_mille(value, rate)
    return value


def allocate(pop: int, slots: Mapping[str, int], allocation: Mapping[str, int], food_room: int | None) -> dict[str, int]:
    """Split a settlement's people between lines.

    Each line first gets its percentage of the people, capped by its slots. Whoever is left
    fills free slots, biggest percentage first. Anyone still left idles. food_room is what
    remains of a food-short civ's cap on food workers (None means no cap).
    """
    if sum(allocation.values()) > 100:
        raise ValueError(f"allocation adds up to more than 100%: {dict(allocation)}")
    caps = {line: slots.get(line, 0) for line in LINES}
    if food_room is not None:
        caps["food"] = min(caps["food"], max(food_room, 0))
    workers = {line: min(floor_div(pop * allocation.get(line, 0), 100), caps[line]) for line in LINES}
    left = pop - sum(workers.values())
    for line in sorted(LINES, key=lambda name: (-allocation.get(name, 0), LINES.index(name))):
        take = min(left, caps[line] - workers[line])
        workers[line] += take
        left -= take
    return workers


def fuel_needed(config: Config, pop: int, season_name: str, harsh: bool) -> int:
    units = config.fuel_winter_units if season_name == "winter" else 1
    need = floor_div(pop * units, config.fuel_people_per_unit)
    return per_mille(need, config.harsh_winter_fuel) if harsh else need


def building_upkeep(config: Config, building_type: str) -> dict[str, int]:
    """Yearly upkeep of one building, paid in the winter tick."""
    extra = config.stone_building_extra_upkeep if building_type in config.stone_buildings else 0
    return {"timber": config.building_timber_upkeep, "stone": config.building_stone_upkeep + extra}


def tool_wear(config: Config, workers: int) -> int:
    return ceil_div(workers, config.tool_wear_workers)


def spoilage(config: Config, food: int, granary: bool) -> int:
    return per_mille(food, config.spoilage_granary if granary else config.spoilage)


def starvation_deaths(config: Config, unfed: int) -> int:
    return ceil_div(unfed, config.starvation_divisor)


def cold_deaths(config: Config, pop: int) -> int:
    return per_mille(pop, config.cold_death_rate)


def growth_rate(config: Config, civ_id: str) -> int:
    return config.culture_growth_rate.get(civ_id, config.growth_rate)


def stability_target(config: Config, *, fed: bool, unfed: int, pop: int, no_winter_fuel: bool, arrears: bool,
                     luxury_recent: bool, modifier: int) -> int:
    target = config.stability_base + modifier
    if fed:
        target += config.stability_fed
    if luxury_recent:
        target += config.stability_luxury
    if pop > 0 and unfed > 0:
        target -= config.stability_unfed_per_10pct * floor_div(unfed * 10, pop)
    if no_winter_fuel:
        target -= config.stability_no_fuel
    if arrears:
        target -= config.stability_arrears
    return target


def stability_next(config: Config, current: int, target: int, shock: int) -> int:
    """Move up to one step towards the target, add any one-off shock, keep within 0 to 100."""
    step = max(-config.stability_step, min(config.stability_step, target - current))
    return max(0, min(100, current + step + shock))


def split_by_weight(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    """Share total out in proportion to weights by largest remainder; ties go to the earlier key.

    No share exceeds its weight while total is at most the sum of weights.
    """
    whole = sum(weights.values())
    if whole == 0 or total == 0:
        return {key: 0 for key in weights}
    shares = {key: floor_div(total * weight, whole) for key, weight in weights.items()}
    rest = total - sum(shares.values())
    order = sorted(weights, key=lambda key: (-((total * weights[key]) % whole), key))
    for key in order[:rest]:
        shares[key] += 1
    return shares


def stage_for(config: Config, pop: int, building_types: Iterable[str]) -> str:
    """Highest growth stage whose population, building count and must-have building are all met.

    building_types lists the settlement's standing (non-ruin) buildings, one entry each.
    """
    types = list(building_types)
    held = set(types)
    best = config.stage_order[0]
    for stage in config.stage_order[1:]:
        needs = config.stage_requires.get(stage, ())
        if (pop < config.stage_min_pop[stage] or len(types) < config.stage_min_buildings[stage]
                or (needs and not held & set(needs))):
            break
        best = stage
    return best
