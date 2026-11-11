"""The tick loop (docs/rules.md section 1).

Runs step 1 (wake and decide), 2 (production and research), 4 (movement, sight, contact),
6 (consumption) and 7 (events, unrest, stability, building, score). Trade (step 3) arrives in
Phase 3 and combat (step 5) in Phase 5. Every stock change goes through ledger.apply; every
draw comes from a fresh rng stream.
"""

from collections.abc import Mapping
from typing import Any

from fogline import construction, ledger, messages, reputation, rng, rules, sight, techs, turns, units, worldgen
from fogline.config import BASICS, RESOURCES, Config
from fogline.intmath import PER_MILLE, ceil_div, floor_div, per_mille
from fogline.layout import EXTRACTION, biome_name, is_land, node_tiles, occupied_tiles
from fogline.ledger import Rule
from fogline.paths import is_river
from fogline.state import parse_tile_key, record_event as _record

WORLD_EVENTS = ("drought", "plague", "harsh_winter", "comet", "mineral_discovery", "flood")
WORK_BUILDINGS = frozenset({"farm", "pasture", "lumber_camp", "mine", "workshop", "library"})
WORK_BY_BUILDING = {"farm": "farm", "pasture": "pasture", "workshop": "research", "library": "research"}
NODE_WORK = {"forest": "timber", "stone": "stone", "metal": "metal"}

Log = list[dict[str, Any]] | None


def tick(config: Config, state: dict, log: Log = None, *,
         deciders: Mapping[str, turns.Decider] | None = None) -> list[turns.TurnRecord]:
    """Advance the world by one season and return the turns taken in it.

    With no deciders nobody is called, but wakes are still kept, so every civ simply sleeps.
    """
    now = state["tick"]
    scratch: dict[str, dict[str, Any]] = {civ: {} for civ in sorted(state["civs"])}
    records = turns.step(config, state, deciders, log)
    _production(config, state, now, log, scratch)
    _research(config, state, now, log)
    units.move_all(config, state, now)
    messages.deliver(config, state, now)  # couriers due this tick, after movement (rules 7)
    sight.update(config, state, now)
    _consumption(config, state, now, log, scratch)
    _events(config, state, now, log, scratch)
    _supply(config, state, log)
    state["tick"] = now + 1
    return records


def run(config: Config, state: dict, ticks: int, log: Log = None, *,
        deciders: Mapping[str, turns.Decider] | None = None) -> list[turns.TurnRecord]:
    # shortcut: every record (with its brief) stays in memory, which suits tests and short runs.
    # A 1,000-tick run should call tick() and write each tick's records out as it goes.
    records: list[turns.TurnRecord] = []
    for _ in range(ticks):
        records += tick(config, state, log, deciders=deciders)
    return records


def _supply(config: Config, state: dict, log: Log) -> None:
    """Test-only stand-in for trade (ADR 0004): raise each civ's basic stocks to config.supply_floor.
    Luxury is left out because a luxury stock lifts stability, and with it every line's output."""
    if not config.supply_floor:
        return
    for civ_id in sorted(state["civs"]):
        stocks = state["civs"][civ_id]["stocks"]
        for resource in BASICS:
            if stocks[resource] < config.supply_floor:
                _apply(state, log, civ_id, stocks, resource, config.supply_floor - stocks[resource], Rule.SUPPLY)


# ---------------------------------------------------------------- helpers


def settlements_of(state: dict, civ_id: str) -> list[str]:
    return sorted(key for key, value in state["settlements"].items() if value["civ"] == civ_id)


def civ_pop(state: dict, civ_id: str) -> int:
    return sum(state["settlements"][sid]["pop"] for sid in settlements_of(state, civ_id))


def _apply(state: dict, log: Log, owner: str, stocks: dict, stock: str, delta: int, rule: Rule) -> None:
    ledger.apply(stocks, state["ledger"], log, owner, stock, delta, rule, state["tick"])


def _active(mods: list[dict], now: int) -> list[dict]:
    return [m for m in mods if m["until"] >= now]


def _in_home_region(config: Config, state: dict, civ_id: str, tile: str) -> bool:
    cx, cy = parse_tile_key(state["settlements"][f"{civ_id}-0"]["tile"])
    x, y = parse_tile_key(tile)
    return (x - cx) ** 2 + (y - cy) ** 2 <= config.home_radius ** 2


def _has_building(settlement: dict, building_type: str) -> bool:
    return any(b["type"] == building_type and not b["ruin"] for b in settlement["buildings"])


def _work_sites(config: Config, state: dict, settlement_id: str, node_at: dict[str, str],
                coastal: set[str]) -> list[dict]:
    """Every place in a settlement where people can work: buildings in order, then fishing, then luxury."""
    settlement = state["settlements"][settlement_id]
    sites = []
    nth: dict[str, int] = {}
    for building in settlement["buildings"]:
        if building["ruin"]:
            continue
        kind = building["type"]
        nth[kind] = nth.get(kind, 0) + 1
        if kind not in WORK_BUILDINGS:
            continue
        node_id = ""
        if kind in ("lumber_camp", "mine"):
            node_id = node_at.get(building["tile"], "")
            node = state["nodes"].get(node_id)
            if node is None or node["kind"] not in NODE_WORK or node["node"] == 0:
                continue  # no node, or worked out: nobody is sent there
            work = NODE_WORK[node["kind"]]
        else:
            work = WORK_BY_BUILDING[kind]
        rate = rules.diminishing(config, nth[kind])
        if building["damaged"] or building["arrears_ticks"] > 0:
            rate = per_mille(rate, config.impaired_rate)
        if kind == "library":
            rate = per_mille(rate, config.library_scholar_rate)
        sites.append({"work": work, "slots": config.slots[kind], "node": node_id,
                      "rate": rate, "tile": building["tile"]})
    if settlement_id in coastal:
        # Any coast in a settlement's land is a fishing ground (rules 21); a harbour widens it.
        slots = config.slots["fishing_harbour" if _has_building(settlement, "harbour") else "fishing_no_harbour"]
        sites.append({"work": "fishing", "slots": slots, "node": "", "rate": PER_MILLE, "tile": settlement["tile"]})
    for node_id, node in sorted(state["nodes"].items()):
        if node["kind"] == "luxury" and state["territory"].get(node["tile"]) == settlement_id:
            sites.append({"work": "luxury", "slots": config.luxury_workers_max, "node": "", "rate": PER_MILLE,
                          "tile": node["tile"]})
    return sites


# ---------------------------------------------------------------- step 2: production


def _production(config: Config, state: dict, now: int, log: Log, scratch: dict) -> None:
    season = rules.season(now)
    harsh = state["world"]["harsh_winter_tick"] == now
    node_at = {node["tile"]: node_id for node_id, node in sorted(state["nodes"].items())}
    coastal = {sid for tile, sid in state["territory"].items() if biome_name(state["map"], tile) == "coast"}
    for civ_id in sorted(state["civs"]):
        civ = state["civs"][civ_id]
        food_room = civ["food_worker_cap"] or None
        budget = [rule["workers"] for rule in civ["reorders"]]
        produced = {line: 0 for line in rules.LINES}
        research_milli = 0
        assigned = 0
        civ_mods = _active(civ["modifiers"], now)
        for settlement_id in settlements_of(state, civ_id):
            settlement = state["settlements"][settlement_id]
            sites = _work_sites(config, state, settlement_id, node_at, coastal)
            if settlement["idle_until"] >= now:
                workers = {line: 0 for line in rules.LINES}
            else:
                slots = {line: 0 for line in rules.LINES}
                for site in sites:
                    slots[rules.WORK_LINE[site["work"]]] += site["slots"]
                capped = food_room is not None and _in_home_region(config, state, civ_id, settlement["tile"])
                workers = rules.allocate(settlement["pop"], slots, civ["allocation"], food_room if capped else None)
                if civ["reorders"]:
                    room = dict(slots)
                    if capped:  # reorders respect a food-short civ's cap too
                        room["food"] = min(slots["food"], max(food_room, workers["food"]))
                    workers, budget = rules.reorder_shift(settlement["pop"], workers, room, civ["stocks"],
                                                          civ["reorders"], budget)
                if capped:
                    food_room -= workers["food"]
            settlement["workers"] = workers
            assigned += sum(workers.values())

            mods = civ_mods + _active(settlement["modifiers"], now)
            sawmill = _has_building(settlement, "sawmill")
            left = dict(workers)
            totals: dict[tuple[str, str], int] = {}
            for site in sites:
                work = site["work"]
                line = rules.WORK_LINE[work]
                count = min(site["slots"], left[line])
                left[line] -= count
                if count == 0:
                    continue
                x, y = parse_tile_key(site["tile"])
                rates = [site["rate"], rules.season_rate(config, work, season)]
                if harsh and work == "farm":
                    rates.append(0)
                rates += [rules.specialty_rate(config, settlement["specialty"], line),
                          rules.tech_rate(config, civ["techs"], work)]
                if sawmill and line == "timber":
                    rates.append(PER_MILLE + config.sawmill_bonus)
                rates.append(rules.stability_rate(config, civ["stability"]))
                if civ["tools_short"]:
                    rates.append(PER_MILLE - config.tool_shortage_penalty)
                for mod in mods:
                    if mod["line"] == line and (not mod["river_only"] or (work == "farm" and is_river(state["map"], x, y))):
                        rates.append(mod["rate"])
                value = rules.apply_rates(count * config.output_per_worker[work] * PER_MILLE, rates)
                key = (line, site["node"])
                totals[key] = totals.get(key, 0) + value
            for (line, node_id), milli in sorted(totals.items()):
                if line == "research":
                    research_milli += milli
                    continue
                amount = floor_div(milli, PER_MILLE)
                if node_id:
                    node = state["nodes"][node_id]
                    amount = min(amount, node["node"])
                    _apply(state, log, node_id, node, "node", -amount, Rule.EXTRACTION)
                _apply(state, log, civ_id, civ["stocks"], line, amount, Rule.PRODUCTION)
                produced[line] += amount
        if any(_has_building(state["settlements"][sid], "printing_house") for sid in settlements_of(state, civ_id)):
            research_milli = per_mille(research_milli, config.printing_rate)
        civ["research"]["points_milli"] += research_milli
        scratch[civ_id].update(food_produced=produced["food"], assigned=assigned)

    for node_id, node in sorted(state["nodes"].items()):
        if node["regrowth"] and node["node"] < node["size"]:
            _apply(state, log, node_id, node, "node", min(node["regrowth"], node["size"] - node["node"]), Rule.REGROWTH)


def _research(config: Config, state: dict, now: int, log: Log) -> None:
    """Spend the civ's points pool on its chosen tech (ADR 0002).

    The pool keeps its points when the ruler switches tech. With no tech chosen the points are
    lost, unless the tree is finished, when they become prestige.
    """
    for civ_id in sorted(state["civs"]):
        civ = state["civs"][civ_id]
        research = civ["research"]
        tech_id = research["tech"]
        if not tech_id:
            if not techs.available(state, civ_id):
                civ["prestige"] += floor_div(research["points_milli"], PER_MILLE)
                research["points_milli"] %= PER_MILLE
            else:
                research["points_milli"] = 0
            continue
        _, price = techs.cost(config, tech_id)
        points = techs.points(config, state, civ_id, tech_id)  # the catch-up discount (rules 14)
        if research["points_milli"] < points * PER_MILLE:
            continue
        if any(civ["stocks"][res] < amount for res, amount in price.items()):
            continue  # finished but unpaid: the pool waits
        for res, amount in sorted(price.items()):
            _apply(state, log, civ_id, civ["stocks"], res, -amount, Rule.RESEARCH_COST)
        research["points_milli"] -= points * PER_MILLE
        research["tech"] = ""
        civ["techs"].append(tech_id)
        _record(state, now, "tech", civ_id, tech_id)


# ---------------------------------------------------------------- step 6: consumption


def _kill(state: dict, log: Log, civ_id: str, deaths: int, rule: Rule) -> None:
    """Spread deaths over a civ's settlements in proportion to their people."""
    pops = {sid: state["settlements"][sid]["pop"] for sid in settlements_of(state, civ_id)}
    for settlement_id, share in rules.split_by_weight(deaths, pops).items():
        _apply(state, log, settlement_id, state["settlements"][settlement_id], "pop", -share, rule)


def _pay_upkeep(config: Config, state: dict, log: Log, civ_id: str, winter: bool) -> bool:
    """Bill every building in winter, then pay every open bill the stock can cover. True if any stays unpaid."""
    stocks = state["civs"][civ_id]["stocks"]
    in_arrears = False
    for settlement_id in settlements_of(state, civ_id):
        for building in state["settlements"][settlement_id]["buildings"]:
            if building["ruin"]:
                continue
            if winter:
                building["owed"] = True
            if not building["owed"]:
                continue
            bill = rules.building_upkeep(config, building["type"])
            if all(stocks[res] >= amount for res, amount in bill.items()):
                for res, amount in sorted(bill.items()):
                    _apply(state, log, civ_id, stocks, res, -amount, Rule.UPKEEP)
                building["owed"] = False
                building["arrears_ticks"] = 0
                continue
            building["arrears_ticks"] += 1
            # Farms, pastures, lumber camps and mines never ruin: they stay at half output, so a
            # civ that runs dry declines to what its land supports instead of dying out (rules 21).
            if building["arrears_ticks"] >= config.ruin_after_ticks and building["type"] not in EXTRACTION:
                building.update(ruin=True, owed=False, arrears_ticks=0)
            else:
                in_arrears = True
    return in_arrears


def _consumption(config: Config, state: dict, now: int, log: Log, scratch: dict) -> None:
    season = rules.season(now)
    winter = season == "winter"
    harsh = state["world"]["harsh_winter_tick"] == now
    for civ_id in sorted(state["civs"]):
        civ = state["civs"][civ_id]
        stocks = civ["stocks"]
        info = scratch[civ_id]
        pop = civ_pop(state, civ_id)

        need = pop * config.food_per_person
        eaten = min(need, stocks["food"])
        _apply(state, log, civ_id, stocks, "food", -eaten, Rule.EATING)
        unit_food = units.pay_upkeep(config, state, civ_id, log)
        unfed = ceil_div(need - eaten, config.food_per_person)

        fuel = rules.fuel_needed(config, pop, season, harsh)
        burnt = min(fuel, stocks["timber"])
        _apply(state, log, civ_id, stocks, "timber", -burnt, Rule.FUEL)
        no_winter_fuel = winter and burnt < fuel

        arrears = _pay_upkeep(config, state, log, civ_id, winter)

        wear = rules.tool_wear(config, info["assigned"])
        civ["tools_short"] = stocks["metal"] < wear
        if not civ["tools_short"]:
            _apply(state, log, civ_id, stocks, "metal", -wear, Rule.TOOL_WEAR)

        if now % config.luxury_use_every == 0:
            for _ in settlements_of(state, civ_id):
                if stocks["luxury"] == 0:
                    break
                _apply(state, log, civ_id, stocks, "luxury", -1, Rule.LUXURY_USE)
                civ["luxury_used_tick"] = now
                civ["luxury_consumed"] += 1

        _kill(state, log, civ_id, rules.starvation_deaths(config, unfed), Rule.DEATH_STARVATION)
        if no_winter_fuel:
            _kill(state, log, civ_id, rules.cold_deaths(config, civ_pop(state, civ_id)), Rule.DEATH_COLD)

        window = civ["food_window"] + [[info["food_produced"], need + unit_food]]
        civ["food_window"] = window[-config.food_window_ticks:]
        surplus = (len(civ["food_window"]) == config.food_window_ticks
                   and sum(p for p, _ in civ["food_window"]) >= sum(c for _, c in civ["food_window"]))
        stored = stocks["food"] >= config.growth_store_ticks * need  # imports can feed growth (rules 4.1)
        if unfed == 0 and (surplus or stored):
            _grow(config, state, log, civ_id)

        granary = _has_building(state["settlements"][f"{civ_id}-0"], "granary")
        _apply(state, log, civ_id, stocks, "food", -rules.spoilage(config, stocks["food"], granary), Rule.SPOILAGE)

        info.update(pop=pop, unfed=unfed, no_winter_fuel=no_winter_fuel, arrears=arrears)


def _grow(config: Config, state: dict, log: Log, civ_id: str) -> None:
    rate = rules.growth_rate(config, civ_id)
    for settlement_id in settlements_of(state, civ_id):
        settlement = state["settlements"][settlement_id]
        housing = sum(1 for b in settlement["buildings"] if b["type"] == "housing" and not b["ruin"])
        room = housing * config.housing_capacity - settlement["pop"]
        if room <= 0:
            continue
        settlement["growth_acc"] += settlement["pop"] * rate
        births = min(floor_div(settlement["growth_acc"], PER_MILLE), room)
        settlement["growth_acc"] %= PER_MILLE
        _apply(state, log, settlement_id, settlement, "pop", births, Rule.BIRTH)


# ---------------------------------------------------------------- step 7: events, unrest, stability, score


def _events(config: Config, state: dict, now: int, log: Log, scratch: dict) -> None:
    if config.events_enabled:
        _providence(config, state, now, log)
        _quirks(config, state, now)
    for civ_id in sorted(state["civs"]):
        _unrest(config, state, now, log, civ_id)
        _update_stability(config, state, now, civ_id, scratch[civ_id])
        _secession(config, state, now, civ_id)
        construction.advance(config, state, now, civ_id, log)
        _score(config, state, civ_id)
        civ = state["civs"][civ_id]
        civ["modifiers"] = [m for m in civ["modifiers"] if m["until"] > now]
        civ["target_mods"] = [m for m in civ["target_mods"] if m["until"] > now]
    for settlement in state["settlements"].values():
        settlement["modifiers"] = [m for m in settlement["modifiers"] if m["until"] > now]
    reputation.drift(config, state, now)
    if state["world"]["harsh_winter_tick"] == now:
        state["world"]["harsh_winter_tick"] = -1


def next_winter(now: int) -> int:
    """The first winter tick after now."""
    return now + 1 + (3 - (now + 1) % 4) % 4


def _damage_building(state: dict, draw, civ_id: str) -> str:
    options = [(sid, index) for sid in settlements_of(state, civ_id)
               for index, b in enumerate(state["settlements"][sid]["buildings"]) if not b["ruin"] and not b["damaged"]]
    if not options:
        return ""
    settlement_id, index = options[draw.randrange(len(options))]
    building = state["settlements"][settlement_id]["buildings"][index]
    building["damaged"] = True
    return f"{building['type']} at {building['tile']}"


def _providence(config: Config, state: dict, now: int, log: Log) -> None:
    seed = state["seed"]
    draw = rng.stream(seed, "events", now, rng.WORLD, "world-event")
    if not rng.chance(draw, config.world_event_chance):
        return
    kind = WORLD_EVENTS[draw.randrange(len(WORLD_EVENTS))]
    civ_ids = sorted(state["civs"])
    civ_id = civ_ids[draw.randrange(len(civ_ids))]
    civ = state["civs"][civ_id]
    own = rng.stream(seed, "events", now, civ_id, kind)

    if kind == "drought":
        civ["modifiers"].append({"line": "food", "rate": config.drought_rate, "until": now + config.drought_ticks,
                                 "river_only": False})
        _record(state, now, kind, civ_id, "")
    elif kind == "plague":
        options = [sid for sid in settlements_of(state, civ_id) if state["settlements"][sid]["pop"] > 0]
        if options:
            settlement_id = options[own.randrange(len(options))]
            settlement = state["settlements"][settlement_id]
            _apply(state, log, settlement_id, settlement, "pop", -per_mille(settlement["pop"], config.plague_loss),
                   Rule.DEATH_PLAGUE)
            civ["shock"] -= config.plague_stability
            _record(state, now, kind, civ_id, settlement_id)
    elif kind == "harsh_winter":
        # Weather falls on the whole world, at the next winter tick.
        state["world"]["harsh_winter_tick"] = next_winter(now)
        _record(state, now, kind, rng.WORLD, str(state["world"]["harsh_winter_tick"]))
    elif kind == "comet":
        for other in civ_ids:
            state["civs"][other]["target_mods"].append({"amount": -config.comet_stability,
                                                        "until": now + config.comet_ticks - 1})
        _record(state, now, kind, rng.WORLD, "")
    elif kind == "mineral_discovery":
        busy = occupied_tiles(state) | node_tiles(state)
        own_land = sorted(sid_tile for sid_tile, sid in state["territory"].items()
                          if state["settlements"][sid]["civ"] == civ_id and sid_tile not in busy
                          and is_land(state["map"], *parse_tile_key(sid_tile)))
        if own_land:
            tile = own_land[own.randrange(len(own_land))]
            node_kind = ("stone", "metal")[own.randrange(2)]
            worldgen.add_node(state, f"found-{now}", node_kind, tile, config.discovery_node_size, 0, civ_id, False,
                              Rule.DISCOVERY, now, log)
            _record(state, now, kind, civ_id, f"{node_kind} at {tile}")
    elif kind == "flood":
        civ["modifiers"].append({"line": "food", "rate": config.flood_rate, "until": now + config.flood_ticks,
                                 "river_only": True})
        _record(state, now, kind, civ_id, _damage_building(state, own, civ_id))


def _quirks(config: Config, state: dict, now: int) -> None:
    for settlement_id in sorted(state["settlements"]):
        settlement = state["settlements"][settlement_id]
        civ_id = settlement["civ"]
        draw = rng.stream(state["seed"], "events", now, civ_id, f"quirk-{settlement_id}")
        if not rng.chance(draw, config.quirk_event_chance):
            continue
        target, sign = config.quirk_effects[settlement["quirk"]]
        if target == "stability":
            state["civs"][civ_id]["shock"] += sign * config.quirk_stability
        else:
            settlement["modifiers"].append({"line": target, "rate": PER_MILLE + sign * config.quirk_line_rate,
                                            "until": now + config.quirk_ticks, "river_only": False})
        _record(state, now, "quirk", civ_id, f"{settlement_id} {settlement['quirk']}")


def _unrest(config: Config, state: dict, now: int, log: Log, civ_id: str) -> None:
    civ = state["civs"][civ_id]
    if civ["stability"] >= config.unrest_below:
        return
    draw = rng.stream(state["seed"], "unrest", now, civ_id, "riot")
    if not rng.chance(draw, config.unrest_chance):
        return
    stocked = [res for res in RESOURCES if civ["stocks"][res] > 0]
    detail = ""
    if stocked:
        res = stocked[draw.randrange(len(stocked))]
        loss = per_mille(civ["stocks"][res], config.riot_stock_loss)
        _apply(state, log, civ_id, civ["stocks"], res, -loss, Rule.RIOT)
        detail = f"{res} -{loss}"
    damaged = _damage_building(state, draw, civ_id)
    _record(state, now, "riot", civ_id, f"{detail}; {damaged}".strip("; "))


def _update_stability(config: Config, state: dict, now: int, civ_id: str, info: dict) -> None:
    civ = state["civs"][civ_id]
    luxury_recent = civ["luxury_used_tick"] >= 0 and now - civ["luxury_used_tick"] < config.luxury_use_every
    target = rules.stability_target(
        config, fed=info["unfed"] == 0, unfed=info["unfed"], pop=info["pop"],
        no_winter_fuel=info["no_winter_fuel"], arrears=info["arrears"], luxury_recent=luxury_recent,
        modifier=sum(m["amount"] for m in _active(civ["target_mods"], now)))
    civ["stability"] = rules.stability_next(config, civ["stability"], target, civ["shock"])
    civ["shock"] = 0


def _secession(config: Config, state: dict, now: int, civ_id: str) -> None:
    civ = state["civs"][civ_id]
    civ["low_stability_ticks"] = civ["low_stability_ticks"] + 1 if civ["stability"] < config.secession_below else 0
    if civ["low_stability_ticks"] < config.secession_ticks:
        return
    civ["low_stability_ticks"] = 0
    options = [sid for sid in settlements_of(state, civ_id)
               if not state["settlements"][sid]["capital"] and state["settlements"][sid]["idle_until"] < now]
    if not options:
        return
    draw = rng.stream(state["seed"], "unrest", now, civ_id, "secession")
    settlement_id = options[draw.randrange(len(options))]
    state["settlements"][settlement_id]["idle_until"] = now + config.secession_idle_ticks
    _record(state, now, "secession", civ_id, settlement_id)


def _score(config: Config, state: dict, civ_id: str) -> None:
    civ = state["civs"][civ_id]
    buildings = sum(1 for sid in settlements_of(state, civ_id)
                    for b in state["settlements"][sid]["buildings"] if not b["ruin"])
    civ["score"] = (civ_pop(state, civ_id) + units.people(state, civ_id) + config.score_per_building * buildings
                    + config.score_per_tech * len(civ["techs"])
                    + floor_div(civ["luxury_consumed"], config.score_luxury_divisor) + civ["prestige"])
