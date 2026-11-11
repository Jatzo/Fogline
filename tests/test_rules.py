"""Each economy formula against a case worked by hand from docs/rules.md sections 3 to 5."""

import pytest

from fogline import rules
from fogline.config import Config

CONFIG = Config()


def test_four_capital_farms_make_51_food_after_diminishing_returns():
    # Rules 4.7: 20 workers on 4 farms at 3 food, rates 1000, 900, 800, 700 -> 15 + 13.5 + 12 + 10.5.
    milli = sum(rules.apply_rates(5 * 3 * 1000, [rules.diminishing(CONFIG, n)]) for n in range(1, 5))
    assert milli // 1000 == 51


def test_diminishing_returns_stop_at_the_floor():
    assert [rules.diminishing(CONFIG, n) for n in (1, 2, 6, 7, 20)] == [1000, 900, 500, 500, 500]


def test_twelve_food_short_workers_make_about_33():
    # Rules 4.7: 12 workers fill 5, 5 and 2 slots -> 15 + 13.5 + 4.8.
    milli = sum(rules.apply_rates(workers * 3 * 1000, [rules.diminishing(CONFIG, n)])
                for n, workers in ((1, 5), (2, 5), (3, 2)))
    assert milli // 1000 == 33


@pytest.mark.parametrize("stability, rate", [(0, 800), (50, 1000), (100, 1200)])
def test_stability_output_multiplier(stability, rate):
    assert rules.stability_rate(CONFIG, stability) == rate


def test_seasons_touch_food_only():
    assert rules.season_rate(CONFIG, "farm", "winter") == 250
    assert rules.season_rate(CONFIG, "pasture", "autumn") == 1500
    assert rules.season_rate(CONFIG, "fishing", "winter") == 750
    assert rules.season_rate(CONFIG, "timber", "winter") == 1000
    assert [rules.season(t) for t in range(5)] == ["spring", "summer", "autumn", "winter", "spring"]


def test_specialty_and_tech_rates():
    specialty = {"strong": "food", "weak": "metal"}
    assert rules.specialty_rate(CONFIG, specialty, "food") == 1400
    assert rules.specialty_rate(CONFIG, specialty, "metal") == 700
    assert rules.specialty_rate(CONFIG, specialty, "timber") == 1000
    assert rules.tech_rate(CONFIG, ["crop_rotation"], "farm") == 1250
    assert rules.tech_rate(CONFIG, ["crop_rotation"], "pasture") == 1000


def test_fuel_for_55_people():
    assert rules.fuel_needed(CONFIG, 55, "spring", harsh=False) == 5
    assert rules.fuel_needed(CONFIG, 55, "winter", harsh=False) == 11  # 2 per 10 in winter
    assert rules.fuel_needed(CONFIG, 55, "winter", harsh=True) == 22


def test_upkeep_tool_wear_spoilage_and_deaths():
    assert rules.building_upkeep(CONFIG, "housing") == {"timber": 1, "stone": 1}
    assert rules.building_upkeep(CONFIG, "library") == {"timber": 1, "stone": 3}
    assert [rules.tool_wear(CONFIG, n) for n in (0, 1, 25, 26)] == [0, 1, 1, 2]
    assert rules.spoilage(CONFIG, 1200, granary=False) == 6
    assert rules.spoilage(CONFIG, 1200, granary=True) == 2
    assert rules.starvation_deaths(CONFIG, 22) == 6
    assert rules.cold_deaths(CONFIG, 55) == 1
    assert rules.growth_rate(CONFIG, "verdance") == 20
    assert rules.growth_rate(CONFIG, "ironhold") == 15


def test_stability_target_cases():
    base = dict(unfed=0, pop=55, no_winter_fuel=False, arrears=False, luxury_recent=False, modifier=0)
    assert rules.stability_target(CONFIG, fed=True, **base) == 60
    assert rules.stability_target(CONFIG, fed=True, **{**base, "luxury_recent": True}) == 65
    # 11 of 55 unfed is 20%: two steps of -2.
    assert rules.stability_target(CONFIG, fed=False, **{**base, "unfed": 11}) == 46
    assert rules.stability_target(CONFIG, fed=True, **{**base, "no_winter_fuel": True, "arrears": True}) == 45


def test_stability_moves_at_most_five_and_stays_in_range():
    assert rules.stability_next(CONFIG, 60, 46, 0) == 55
    assert rules.stability_next(CONFIG, 60, 58, 0) == 58
    assert rules.stability_next(CONFIG, 3, 0, -10) == 0
    assert rules.stability_next(CONFIG, 98, 100, 3) == 100


def test_allocation_fills_by_percentage_then_by_priority():
    slots = {"food": 20, "timber": 5, "stone": 4, "research": 4, "luxury": 2}
    workers = rules.allocate(40, slots, CONFIG.default_allocation, None)
    assert workers == {"food": 20, "timber": 5, "stone": 4, "metal": 0, "luxury": 2, "research": 4}
    capped = rules.allocate(40, slots, CONFIG.default_allocation, 12)
    assert capped["food"] == 12 and sum(capped.values()) == 27


def test_allocation_moves_spare_people_to_free_slots():
    workers = rules.allocate(10, {"food": 5, "timber": 5}, {"food": 20, "timber": 10}, None)
    assert workers["food"] == 5 and workers["timber"] == 5


def test_allocation_over_100_percent_is_refused():
    with pytest.raises(ValueError):
        rules.allocate(10, {"food": 5}, {"food": 80, "timber": 30}, None)


def test_split_by_weight_uses_largest_remainder():
    assert rules.split_by_weight(7, {"a": 10, "b": 20, "c": 30}) == {"a": 1, "b": 2, "c": 4}
    assert rules.split_by_weight(0, {"a": 5}) == {"a": 0}
    assert rules.split_by_weight(3, {"a": 1, "b": 1, "c": 1}) == {"a": 1, "b": 1, "c": 1}
