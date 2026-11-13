"""Trade between civs: offers, escrow, caravans and delivery (docs/rules.md section 8, ADR 0008).

An offer moves the giver's goods out of its stockpile into escrow at once (owner offer-<id>-give)
and reserves its caravans. Accepting does the same for the receiver's side (offer-<id>-get).
Each side then travels as a caravan leg on the real map, carrying its goods as cargo, and
delivers on arrival, less the market fee, which is destroyed. Expiry or rejection returns the
escrow. Every unit of every good moves through the ledger, so conservation covers escrow and
goods in transit; a blueprint is not a stock, so it is minted and spent as logged events.
"""

from fogline import ledger, messages, paths, reputation, techs
from fogline.config import RESOURCES, Config
from fogline.intmath import PER_MILLE, ceil_div, floor_div
from fogline.ledger import Rule
from fogline.state import parse_tile_key, record_event

BLUEPRINT = "blueprint:"
OPEN, ACCEPTED, MOVING, DONE, EXPIRED, REJECTED = "open", "accepted", "moving", "done", "expired", "rejected"
LIVE = (OPEN, ACCEPTED, MOVING)


def is_good(good: str) -> bool:
    return good in RESOURCES or (good.startswith(BLUEPRINT) and good[len(BLUEPRINT):] in techs.TECHS)


def size(goods: dict) -> int:
    return sum(goods.values())


def capacity(config: Config, state: dict, civ_id: str) -> int:
    return config.caravan_capacity * (2 if "carts" in state["civs"][civ_id]["techs"] else 1)


def caravans_needed(config: Config, state: dict, civ_id: str, goods: dict) -> int:
    return ceil_div(size(goods), capacity(config, state, civ_id)) if goods else 0


def free_caravans(state: dict, civ_id: str) -> list[str]:
    return sorted(uid for uid, u in state["units"].items()
                  if u["civ"] == civ_id and u["kind"] == "caravan" and state["tick"] >= u["ready_tick"]
                  and not u["reserved"])


def value(config: Config, state: dict, goods: dict) -> int:
    """What goods are worth in food: each at its last price against food, else its base value."""
    total_milli = 0
    for good, amount in goods.items():
        if good.startswith(BLUEPRINT):
            total_milli += amount * config.blueprint_value_per_era * techs.TECHS[good[len(BLUEPRINT):]].era * PER_MILLE
        else:
            total_milli += amount * state["prices"].get(good, config.base_value[good] * PER_MILLE)
    return floor_div(total_milli, PER_MILLE)


def can_hold(state: dict, civ_id: str, goods: dict) -> bool:
    civ = state["civs"][civ_id]
    for good, amount in goods.items():
        if good.startswith(BLUEPRINT):
            if amount != 1 or good[len(BLUEPRINT):] not in civ["techs"]:
                return False
        elif civ["stocks"][good] < amount:
            return False
    return True


def _escrow(state: dict, log: list | None, civ_id: str, offer: dict, side: str) -> None:
    """Move one side's goods from the civ into the offer's escrow, minting any blueprint."""
    civ, held, owner = state["civs"][civ_id], offer["escrow"][side], f"offer-{offer['id']}-{side}"
    for good, amount in sorted(offer[side].items()):
        if good.startswith(BLUEPRINT):
            record_event(state, state["tick"], "blueprint_minted", civ_id, f"{good} {offer['id']}")
            continue
        ledger.apply(civ["stocks"], state["ledger"], log, civ_id, good, -amount, Rule.ESCROW, state["tick"])
        ledger.apply(held, state["ledger"], log, owner, good, amount, Rule.ESCROW, state["tick"])


def _unescrow(state: dict, log: list | None, civ_id: str, offer: dict, side: str) -> None:
    civ, held, owner = state["civs"][civ_id], offer["escrow"][side], f"offer-{offer['id']}-{side}"
    for good, amount in sorted(held.items()):
        if amount:
            ledger.apply(held, state["ledger"], log, owner, good, -amount, Rule.ESCROW_RETURN, state["tick"])
            ledger.apply(civ["stocks"], state["ledger"], log, civ_id, good, amount, Rule.ESCROW_RETURN, state["tick"])
    for good in sorted(offer[side]):
        if good.startswith(BLUEPRINT):  # minted for this offer and never delivered
            record_event(state, state["tick"], "blueprint_destroyed", civ_id, f"{good} {offer['id']}")
    for uid in offer["caravans"][side]:
        if uid in state["units"]:
            state["units"][uid]["reserved"] = ""


def offer(config: Config, state: dict, giver: str, receiver: str, give: dict, get: dict, expires_in: int,
          log: list | None) -> str:
    """Make an offer (the caller has checked it): escrow the giver's goods and reserve caravans."""
    offer_id = f"o{state['next_offer']}"
    state["next_offer"] += 1
    record = {"id": offer_id, "from": giver, "to": receiver, "give": dict(sorted(give.items())),
              "get": dict(sorted(get.items())), "made": state["tick"], "expires": state["tick"] + expires_in,
              "status": OPEN, "escrow": {"give": {}, "get": {}}, "caravans": {"give": [], "get": []},
              "delivered": {"give": False, "get": not get}}
    state["offers"][offer_id] = record
    record["caravans"]["give"] = free_caravans(state, giver)[:caravans_needed(config, state, giver, give)]
    for uid in record["caravans"]["give"]:
        state["units"][uid]["reserved"] = offer_id
    _escrow(state, log, giver, record, "give")
    record_event(state, state["tick"], "offer", receiver, giver)
    return offer_id


def accept(config: Config, state: dict, record: dict, log: list | None) -> None:
    receiver = record["to"]
    record["caravans"]["get"] = free_caravans(state, receiver)[:caravans_needed(config, state, receiver, record["get"])]
    for uid in record["caravans"]["get"]:
        state["units"][uid]["reserved"] = record["id"]
    _escrow(state, log, receiver, record, "get")
    record["status"] = ACCEPTED


def reject(state: dict, record: dict, log: list | None) -> None:
    _unescrow(state, log, record["from"], record, "give")
    record["status"] = REJECTED


def _nearest(state: dict, civ_id: str, tile: str) -> str:
    x, y = parse_tile_key(tile)
    own = sorted((max(abs(sx - x), abs(sy - y)), sid) for sid, s in state["settlements"].items() if s["civ"] == civ_id
                 for sx, sy in [parse_tile_key(s["tile"])])
    return state["settlements"][own[0][1]]["tile"]


def _route_leg(config: Config, state: dict, unit: dict, sender: str, receiver: str) -> tuple[list[str], str]:
    """Home first if the caravan isn't at a settlement of its own, then to the receiver's nearest
    settlement (rules 21). On the true map: a caravan's path isn't a ruler's guess."""
    from fogline import units  # units imports nothing from here; kept local to keep the module light
    start = unit["tile"]
    own_tiles = {s["tile"] for s in state["settlements"].values() if s["civ"] == sender}
    home = start if start in own_tiles else _nearest(state, sender, start)
    first = units.route(config, state, start, home) or [] if home != start else []
    destination = _nearest(state, receiver, home)
    second = units.route(config, state, home, destination)
    if second is None:  # the capitals are joined (checked when offered); go capital to capital
        second = units.route(config, state, home, state["settlements"][f"{receiver}-0"]["tile"]) or []
        destination = state["settlements"][f"{receiver}-0"]["tile"]
    return first + second, destination


def step(config: Config, state: dict, now: int, log: list | None) -> None:
    """The trade step, after research: warn of offers about to expire, expire open offers whose
    time is up, and send accepted ones on their way as caravan legs."""
    for offer_id in sorted(state["offers"]):
        record = state["offers"][offer_id]
        if record["status"] == OPEN and now == record["expires"] - 1:
            record_event(state, now, "offer_expiring", record["to"], record["from"])
        if record["status"] == OPEN and now >= record["expires"]:
            _unescrow(state, log, record["from"], record, "give")
            record["status"] = EXPIRED
            record_event(state, now, "offer_expired", record["from"], record["to"])
        elif record["status"] == ACCEPTED:
            for side, sender, receiver in (("give", record["from"], record["to"]), ("get", record["to"], record["from"])):
                _load(config, state, log, record, side, sender, receiver)
            record["status"] = MOVING


def _load(config: Config, state: dict, log: list | None, record: dict, side: str, sender: str, receiver: str) -> None:
    caravans = record["caravans"][side]
    held, owner = record["escrow"][side], f"offer-{record['id']}-{side}"
    room = capacity(config, state, sender)
    loads = {uid: {} for uid in caravans}
    goods = sorted(record[side].items())
    for uid in caravans:  # fill each caravan in turn
        space = room
        for i, (good, amount) in enumerate(goods):
            take = min(space, amount)
            if take:
                loads[uid][good] = take
                goods[i] = (good, amount - take)
                space -= take
    for uid in caravans:
        unit = state["units"][uid]
        blueprints = sorted(g for g in loads[uid] if g.startswith(BLUEPRINT))  # not stocks: carried by name
        for good, amount in sorted(loads[uid].items()):
            if not good.startswith(BLUEPRINT):
                ledger.apply(held, state["ledger"], log, owner, good, -amount, Rule.LOADED, state["tick"])
                ledger.apply(unit["cargo"], state["ledger"], log, uid, good, amount, Rule.LOADED, state["tick"])
        path, destination = _route_leg(config, state, unit, sender, receiver)
        unit["path"], unit["target"], unit["idle_since"] = path, destination, -1
        unit["leg"] = {"offer": record["id"], "side": side, "to": receiver, "at": destination, "blueprints": blueprints}


def fee_rate(config: Config, state: dict, receiver: str, giver: str) -> int:
    has_market = any(b["type"] == "market" and not b["ruin"] for s in state["settlements"].values()
                     if s["civ"] == receiver for b in s["buildings"])
    rate = config.culture_market_fee.get(receiver, config.market_fee_with_market) if has_market else config.market_fee
    if state["reputation"][receiver][giver] >= config.fee_halving_view:
        rate //= 2
    return rate


def deliver(config: Config, state: dict, now: int, log: list | None) -> None:
    """After movement: each caravan that has reached its destination hands over its cargo, less the
    fee per good (rounded down, destroyed). Blueprints unlock a tech the buyer can use, or are
    destroyed. A side counts as delivered when its last caravan arrives."""
    for uid in sorted(state["units"]):
        unit = state["units"][uid]
        leg = unit["leg"]
        if not leg or unit["path"] or unit["tile"] != leg["at"]:
            continue
        record = state["offers"][leg["offer"]]
        receiver, giver = leg["to"], unit["civ"]
        rate = fee_rate(config, state, receiver, giver)
        stocks = state["civs"][receiver]["stocks"]
        for good in leg["blueprints"]:
            tech = good[len(BLUEPRINT):]
            held = state["civs"][receiver]["techs"]
            if tech not in held and techs.prereqs_met(held, tech):
                held.append(tech)
                record_event(state, now, "tech", receiver, tech)
            else:
                record_event(state, now, "blueprint_destroyed", receiver, tech)
        for good, amount in sorted(unit["cargo"].items()):
            fee = floor_div(amount * rate, PER_MILLE)
            if fee:
                ledger.apply(unit["cargo"], state["ledger"], log, uid, good, -fee, Rule.MARKET_FEE, now)
            if amount - fee:
                ledger.apply(unit["cargo"], state["ledger"], log, uid, good, -(amount - fee), Rule.TRADE_DELIVERY, now)
                ledger.apply(stocks, state["ledger"], log, receiver, good, amount - fee, Rule.TRADE_DELIVERY, now)
        unit["leg"], unit["reserved"] = {}, ""
        record_event(state, now, "delivered", receiver, f"{giver} {record['id']}")
        side = leg["side"]
        if not any(state["units"][u]["leg"].get("offer") == record["id"] and state["units"][u]["leg"]["side"] == side
                   for u in record["caravans"][side] if u in state["units"]):
            _side_done(config, state, record, side)


def _side_done(config: Config, state: dict, record: dict, side: str) -> None:
    record["delivered"][side] = True
    giver, receiver = (record["from"], record["to"]) if side == "give" else (record["to"], record["from"])
    if not record["get"]:  # aid (rules 11): +1 per 20 value, at most +10
        reputation.change(state, receiver, giver, min(10, value(config, state, record["give"]) // 20))
    else:
        reputation.change(state, receiver, giver, 3)
        sent, back = value(config, state, record["give"]), value(config, state, record["get"])
        if back and abs(sent - back) * PER_MILLE <= config.fair_trade_margin * max(sent, back):
            reputation.change(state, receiver, giver, 2)
    if record["delivered"]["give"] and record["delivered"]["get"]:
        record["status"] = DONE
        _price(state, record)


def _price(state: dict, record: dict) -> None:
    """A trade of one good against food sets that good's price in food (per mille)."""
    give, get = record["give"], record["get"]
    if len(give) == 1 and len(get) == 1:
        (a, qa), (b, qb) = next(iter(give.items())), next(iter(get.items()))
        if a == "food" and b in RESOURCES and b != "food":
            state["prices"][b] = qa * PER_MILLE // qb
        elif b == "food" and a in RESOURCES and a != "food":
            state["prices"][a] = qb * PER_MILLE // qa


def joined(config: Config, state: dict, a: str, b: str) -> bool:
    return messages.delivery_tick(config, state, a, b) is not None
