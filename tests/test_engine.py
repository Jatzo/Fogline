"""Economy tick tests: conservation over long runs, plus engine behaviour the formulas alone can't show."""

import copy
import dataclasses

import pytest

from fogline import engine, ledger, units, worldgen
from fogline.config import RESOURCES, Config
from fogline.state import state_hash

CONFIG = Config()
QUIET = dataclasses.replace(CONFIG, events_enabled=False)


@pytest.fixture(scope="module")
def start():
    return worldgen.generate(CONFIG, 1)


def _fresh(start):
    return copy.deepcopy(start)


def _assert_conserved(state):
    totals = state["ledger"]
    for civ_id, civ in state["civs"].items():
        for stock, value in civ["stocks"].items():
            assert ledger.net_change(totals, civ_id, stock) == value, (civ_id, stock)
    for settlement_id, settlement in state["settlements"].items():
        assert ledger.net_change(totals, settlement_id, "pop") == settlement["pop"], settlement_id
    for node_id, node in state["nodes"].items():
        assert ledger.net_change(totals, node_id, "node") == node["node"], node_id
    for unit_id, unit in state["units"].items():
        assert ledger.net_change(totals, unit_id, "pop") == unit["pop"], unit_id
        for resource in RESOURCES:  # goods in transit on a caravan
            assert ledger.net_change(totals, unit_id, resource) == unit.get("cargo", {}).get(resource, 0), (unit_id, resource)
    escrow = {}
    for offer in state.get("offers", {}).values():  # goods held by an offer
        for side in ("give", "get"):
            escrow[f"offer-{offer['id']}-{side}"] = offer["escrow"][side]
    for owner, held in escrow.items():
        for stock in ledger.STOCKS:
            assert ledger.net_change(totals, owner, stock) == held.get(stock, 0), (owner, stock)
    # A transfer moves goods between owners, so across all owners it must net to zero.
    for rule in (ledger.Rule.ESCROW, ledger.Rule.ESCROW_RETURN, ledger.Rule.LOADED, ledger.Rule.TRADE_DELIVERY):
        for stock in ledger.STOCKS:
            moved = sum(v for k, v in totals.items() if k.endswith(f":{stock}:{rule.value}"))
            assert moved == 0, (rule.value, stock, moved)
    # An owner that no longer exists (a disbanded unit) must hold nothing of anything.
    live = set(state["civs"]) | set(state["settlements"]) | set(state["nodes"]) | set(state["units"]) | set(escrow)
    gone = {key.split(":")[0] for key in totals} - live
    for owner in gone:
        for stock in ledger.STOCKS:
            assert ledger.net_change(totals, owner, stock) == 0, (owner, stock)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_stock_is_explained_by_the_ledger_over_200_ticks(seed):
    state = worldgen.generate(CONFIG, seed)
    before = dict(state["ledger"])
    log = []
    engine.run(CONFIG, state, 200, log)
    _assert_conserved(state)
    # The per-tick log explains exactly what the running totals gained during the run.
    summed = {}
    for entry in log:
        key = f"{entry['owner']}:{entry['stock']}:{entry['rule']}"
        summed[key] = summed.get(key, 0) + entry["delta"]
    gained = {key: value - before.get(key, 0) for key, value in state["ledger"].items()
              if value != before.get(key, 0)}
    assert {k: v for k, v in summed.items() if v} == gained


def test_conservation_holds_through_riots_and_secession(start):
    state = _fresh(start)
    for _ in range(40):  # hold every civ in turmoil
        for civ in state["civs"].values():
            civ["stability"] = 0
        engine.tick(CONFIG, state)
    kinds = {event["kind"] for event in state["events"]}
    assert {"riot", "secession"} <= kinds
    _assert_conserved(state)


def test_every_world_event_keeps_the_ledger_whole(start):
    state = _fresh(start)
    stormy = dataclasses.replace(CONFIG, world_event_chance=1000)
    engine.run(stormy, state, 60)
    kinds = {event["kind"] for event in state["events"]}
    assert set(engine.WORLD_EVENTS) <= kinds, kinds
    assert any(node_id.startswith("found-") for node_id in state["nodes"])
    _assert_conserved(state)


@pytest.mark.parametrize("now, winter", [(0, 3), (2, 3), (3, 7), (5, 7)])
def test_harsh_winter_lands_on_the_next_winter(now, winter):
    assert engine.next_winter(now) == winter


def test_the_same_start_gives_the_same_hash(start):
    first, second = _fresh(start), _fresh(start)
    engine.run(CONFIG, first, 50)
    engine.run(CONFIG, second, 50)
    assert state_hash(first) == state_hash(second)


def test_first_tick_production_for_a_normal_capital(start):
    state = _fresh(start)
    capital = state["settlements"]["verdance-0"]
    engine.tick(QUIET, state)
    # 40 people, default allocation: 20 farmers, 5 foresters, 4 at the mine, 2 on luxury, 4 scholars.
    workers = capital["workers"]
    assert workers["food"] == 20 and workers["timber"] == 5 and workers["research"] == 4
    assert workers["luxury"] == 2
    assert sum(workers.values()) <= capital["pop"]


def test_food_short_civ_keeps_to_its_worker_cap(start):
    state = _fresh(start)
    engine.tick(QUIET, state)
    for civ_id, civ in state["civs"].items():
        food = sum(state["settlements"][sid]["workers"]["food"] for sid in engine.settlements_of(state, civ_id))
        if civ["food_worker_cap"]:
            assert food <= civ["food_worker_cap"], civ_id
        else:
            assert food > QUIET.short_food_worker_cap, civ_id


def test_no_growth_before_a_full_four_tick_food_window(start):
    state = _fresh(start)
    births = lambda s: sum(v for k, v in s["ledger"].items() if k.endswith(":pop:birth"))  # noqa: E731
    engine.run(QUIET, state, 3)
    assert births(state) == 0
    engine.run(QUIET, state, 12)
    assert births(state) > 0


def test_a_civ_short_of_food_grows_only_on_a_deep_store(start):
    # Ironhold's farms never cover its eating, so only the stored-food clause can let it grow (rules 4.1).
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    civ, capital = state["civs"]["ironhold"], state["settlements"]["ironhold-0"]
    window = civ["food_window"]
    assert sum(p for p, _ in window) < sum(c for _, c in window)

    def store(ticks_of_eating):
        target = ticks_of_eating * engine.civ_pop(state, "ironhold") * QUIET.food_per_person
        ledger.apply(civ["stocks"], state["ledger"], None, "ironhold", "food", target - civ["stocks"]["food"],
                     ledger.Rule.PRODUCTION, state["tick"])

    store(QUIET.growth_store_ticks // 2)
    before = capital["growth_acc"]
    engine.tick(QUIET, state)
    assert capital["growth_acc"] == before  # half the store the rule asks for: no growth

    store(QUIET.growth_store_ticks * 2)
    engine.tick(QUIET, state)
    assert capital["growth_acc"] != before
    _assert_conserved(state)


def test_the_growth_window_counts_what_units_eat(start):
    # Rules 4.1: production must cover consumption, and units' food is consumption. Verdance's window is
    # set so that its next tick's production covers its people exactly but not its units as well.
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    civ = state["civs"]["verdance"]
    units.spawn(QUIET, state, "verdance", "levy", "verdance-0", None, pay=False, ready_now=True)
    need = engine.civ_pop(state, "verdance") * QUIET.food_per_person
    stock = need + 10  # everyone eats, units are paid, and the 40-tick store clause stays shut
    ledger.apply(civ["stocks"], state["ledger"], None, "verdance", "food", stock - civ["stocks"]["food"],
                 ledger.Rule.PRODUCTION, state["tick"])

    probe = copy.deepcopy(state)
    engine.tick(QUIET, probe)
    produced, consumed = probe["civs"]["verdance"]["food_window"][-1]
    unit_food = consumed - need
    assert unit_food == 2  # the starting scout and the levy, 1 each

    def grows_with(margin):
        trial = copy.deepcopy(state)
        trial["civs"]["verdance"]["food_window"] = [[max(margin, 0), max(-margin, 0)], [0, 0], [0, 0]]
        before = trial["settlements"]["verdance-0"]["growth_acc"]
        engine.tick(QUIET, trial)
        return trial["settlements"]["verdance-0"]["growth_acc"] != before

    assert not grows_with(need - produced)  # covers the people only
    assert grows_with(need + unit_food - produced)  # covers people and units
    _assert_conserved(probe)


def test_starving_civ_loses_a_quarter_of_its_unfed_rounded_up(start):
    state = _fresh(start)
    civ = state["civs"]["ironhold"]
    ledger.apply(civ["stocks"], state["ledger"], None, "ironhold", "food", -civ["stocks"]["food"],
                 ledger.Rule.RIOT, 0)
    pop = engine.civ_pop(state, "ironhold")
    engine.tick(QUIET, state)
    produced = state["ledger"]["ironhold:food:production"]
    unfed = pop - produced
    deaths = -sum(v for k, v in state["ledger"].items()
                  if k.startswith("ironhold-") and k.endswith(":pop:death_starvation"))
    assert deaths == -(-unfed // 4)
    # With nothing to eat the starting scout can't be fed either, so its person comes home.
    assert "ironhold-u0" not in state["units"]
    assert civ["stability"] < QUIET.stability_start


def test_unpaid_upkeep_ruins_buildings_after_eight_ticks_but_never_fields_or_camps(start):
    state = _fresh(start)
    civ = state["civs"]["frostmark"]
    ledger.apply(civ["stocks"], state["ledger"], None, "frostmark", "stone", -civ["stocks"]["stone"],
                 ledger.Rule.RIOT, 0)
    capital = state["settlements"]["frostmark-0"]
    # Keep the mine off stone so nothing pays the bill.
    civ["allocation"] = {"food": 100}
    engine.run(QUIET, state, 4)
    assert all(b["arrears_ticks"] == 1 for b in capital["buildings"])
    engine.run(QUIET, state, 7)
    assert all(b["arrears_ticks"] == 8 or b["ruin"] for b in capital["buildings"])
    engine.tick(QUIET, state)
    for building in capital["buildings"]:
        if building["type"] in engine.EXTRACTION:  # farms, camps and mines stay, at half output
            assert not building["ruin"] and building["arrears_ticks"] > QUIET.ruin_after_ticks
        else:
            assert building["ruin"]
    _assert_conserved(state)


def test_events_are_off_when_disabled(start):
    state = _fresh(start)
    engine.run(QUIET, state, 100)
    assert not [e for e in state["events"] if e["kind"] in (*engine.WORLD_EVENTS, "quirk")]


# Rules only the conservation sweeps touched until the Phase 1 review. Each compares one tick of
# two copies of the same state that differ in one thing, so the difference is that thing alone.

def _twin_tick(state, change):
    """Tick a copy as it is and a copy with change applied; return (as is, changed) after the tick."""
    plain, changed = copy.deepcopy(state), copy.deepcopy(state)
    change(changed)
    engine.tick(QUIET, plain)
    engine.tick(QUIET, changed)
    return plain, changed


def _food_made(state, civ_id):
    return state["civs"][civ_id]["food_window"][-1][0]


def test_a_tool_shortage_costs_a_fifth_of_output_and_takes_no_metal(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    civ = state["civs"]["verdance"]
    worn = lambda s: s["ledger"].get("verdance:metal:tool_wear", 0)  # noqa: E731
    before = worn(state)
    with monkeypatch.context() as patch:
        patch.setattr(engine.rules, "tool_wear", lambda config, workers: 10 ** 6)
        engine.tick(QUIET, state)
    assert civ["tools_short"] and worn(state) == before

    short, whole = _twin_tick(state, lambda s: s["civs"]["verdance"].update(tools_short=False))
    made, full = _food_made(short, "verdance"), _food_made(whole, "verdance")
    assert made < full
    assert abs(made * 1000 - full * (1000 - QUIET.tool_shortage_penalty)) <= 1000 * 20  # per-site rounding
    _assert_conserved(short)


def test_a_winter_without_fuel_kills_the_cold_death_share(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, 3)
    assert engine.rules.season(state["tick"]) == "winter"
    civ = state["civs"]["verdance"]
    ledger.apply(civ["stocks"], state["ledger"], None, "verdance", "food", 10 ** 5, ledger.Rule.PRODUCTION,
                 state["tick"])  # nobody starves, so cold is the only death
    pop = engine.civ_pop(state, "verdance")
    cold = lambda s: sum(v for k, v in s["ledger"].items()  # noqa: E731
                         if k.startswith("verdance") and k.endswith(":pop:death_cold"))
    monkeypatch.setattr(engine.rules, "fuel_needed", lambda config, pop, season, harsh: 10 ** 6)
    engine.tick(QUIET, state)
    assert cold(state) == -engine.rules.cold_deaths(QUIET, pop) < 0
    _assert_conserved(state)


def test_a_luxury_use_takes_one_per_settlement_and_holds_the_bonus_four_ticks(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, QUIET.luxury_use_every)
    now = state["tick"]
    assert now % QUIET.luxury_use_every == 0
    civ = state["civs"]["verdance"]
    count = len(engine.settlements_of(state, "verdance"))
    ledger.apply(civ["stocks"], state["ledger"], None, "verdance", "luxury", count, ledger.Rule.PRODUCTION, now)
    used = lambda: state["ledger"].get("verdance:luxury:luxury_use", 0)  # noqa: E731
    before = used()
    engine.tick(QUIET, state)
    assert used() - before == -count and civ["luxury_used_tick"] == now

    seen = []
    real = engine.rules.stability_target
    monkeypatch.setattr(engine.rules, "stability_target",
                        lambda config, **kw: seen.append(kw["luxury_recent"]) or real(config, **kw))
    info = {"unfed": 0, "pop": engine.civ_pop(state, "verdance"), "no_winter_fuel": False, "arrears": False}
    for tick in range(now, now + QUIET.luxury_use_every + 1):
        engine._update_stability(QUIET, state, tick, "verdance", info)
    assert seen == [True] * QUIET.luxury_use_every + [False]


def _force_event(monkeypatch, kind, state):
    """Make the world event on the next tick certain and of one kind, then tick with events on."""
    with monkeypatch.context() as patch:
        patch.setattr(engine, "WORLD_EVENTS", (kind,))
        patch.setattr(engine, "_quirks", lambda config, state, now: None)
        engine.tick(dataclasses.replace(CONFIG, world_event_chance=1000), state)


def test_a_drought_cuts_food_for_its_ticks_then_lifts(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    struck = state["tick"]
    _force_event(monkeypatch, "drought", state)
    civ_id = next(e["civ"] for e in state["events"] if e["kind"] == "drought" and e["tick"] == struck)
    for _ in range(QUIET.drought_ticks):  # production ticks struck+1 .. struck+D
        assert state["civs"][civ_id]["modifiers"]
        dry, clear = _twin_tick(state, lambda s: s["civs"][civ_id].update(modifiers=[]))
        assert _food_made(dry, civ_id) < _food_made(clear, civ_id)
        state = dry
    assert state["tick"] == struck + 1 + QUIET.drought_ticks
    assert not state["civs"][civ_id]["modifiers"]


def test_a_comet_lowers_every_stability_target_for_its_ticks(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    mods = []
    real = engine.rules.stability_target
    monkeypatch.setattr(engine.rules, "stability_target",
                        lambda config, **kw: mods.append(kw["modifier"]) or real(config, **kw))
    _force_event(monkeypatch, "comet", state)  # the comet lands before stability, so it counts this tick
    for _ in range(QUIET.comet_ticks):
        engine.tick(QUIET, state)
    civs = len(state["civs"])
    per_tick = [mods[i:i + civs] for i in range(0, len(mods), civs)]
    assert per_tick == [[-QUIET.comet_stability] * civs] * QUIET.comet_ticks + [[0] * civs]


def test_a_seceded_town_idles_for_its_ticks_then_works_again(start, monkeypatch):
    state = _fresh(start)
    engine.run(QUIET, state, 4)
    civ = state["civs"]["verdance"]
    civ.update(stability=0, low_stability_ticks=QUIET.secession_ticks - 1)
    seceded_at = state["tick"]
    engine.tick(QUIET, state)
    idle = [sid for sid in engine.settlements_of(state, "verdance") if state["settlements"][sid]["idle_until"] >= 0]
    assert len(idle) == 1 and state["settlements"][idle[0]]["idle_until"] == seceded_at + QUIET.secession_idle_ticks

    assigned = []
    real = engine.rules.tool_wear
    monkeypatch.setattr(engine.rules, "tool_wear",
                        lambda config, workers: assigned.append(workers) or real(config, workers))
    order = sorted(state["civs"]).index("verdance")

    def working_people(s):
        """Verdance's assigned workers on the next tick."""
        assigned.clear()
        engine.tick(QUIET, s)
        return assigned[order]

    for offset in range(1, QUIET.secession_idle_ticks + 2):  # ticks t+1 .. t+S+1
        working = copy.deepcopy(state)
        working["settlements"][idle[0]]["idle_until"] = -1
        free, held = working_people(working), working_people(state)
        assert (held < free) if offset <= QUIET.secession_idle_ticks else (held == free), offset
    _assert_conserved(state)
