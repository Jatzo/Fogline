"""Ruler actions, each checked before it touches state (docs/rules.md section 16).

dispatch() is the only way in for an agent's action: it checks the shape, turns tiles relative
to the civ's origin into map tiles, and calls the handler. Each handler returns None when the
action is accepted and applied, or a Reason when it is rejected; a rejected action changes
nothing. action_table() is the one list of actions; the tool schema is exported from it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from fogline import construction, memory, messages, rules, sight, techs, units
from fogline.config import Config
from fogline.state import parse_tile_key, tile_key

Log = list[dict] | None


class Reason(StrEnum):
    """Every rejection code. The M4 strings keep their values."""

    MALFORMED = "malformed"
    UNPARSEABLE_REPLY = "unparseable_reply"
    UNKNOWN_ACTION = "unknown_action"
    OVER_ACTION_CAP = "over_action_cap"
    BAD_ARGS = "bad_args"
    BAD_TILE = "bad_tile"
    BAD_END_TURN = "bad_end_turn"
    BAD_MEMORY = "bad_memory"
    UNKNOWN_CIV = "unknown_civ"
    UNKNOWN_TECH = "unknown_tech"
    ALREADY_KNOWN = "already_known"
    PREREQS_MISSING = "prereqs_missing"
    GATE_UNMET = "gate_unmet"
    UNKNOWN_BUILDING = "unknown_building"
    NOT_OWN_SETTLEMENT = "not_own_settlement"
    TECH_MISSING = "tech_missing"
    QUEUE_FULL = "queue_full"
    TILE_TAKEN = "tile_taken"
    ALREADY_QUEUED = "already_queued"
    NO_TILE = "no_tile"
    BAD_ALLOCATION = "bad_allocation"
    UNKNOWN_UNIT_KIND = "unknown_unit_kind"
    BUILDING_MISSING = "building_missing"
    CANNOT_AFFORD = "cannot_afford"
    NOT_ENOUGH_PEOPLE = "not_enough_people"
    UNKNOWN_UNIT = "unknown_unit"
    IN_TRAINING = "in_training"
    UNKNOWN_GROUND = "unknown_ground"
    UNREACHABLE = "unreachable"
    NOT_IN_TERRITORY = "not_in_territory"
    BAD_NOTE = "bad_note"
    TOO_MANY_MESSAGES = "too_many_messages"
    EMPTY_MESSAGE = "empty_message"


# ------------------------------------------------------------------ handlers


def set_research(config: Config, state: dict, civ_id: str, tech: str, log: Log = None) -> Reason | None:
    civ = state["civs"].get(civ_id)
    if civ is None:
        return Reason.UNKNOWN_CIV
    if tech not in techs.TECHS:
        return Reason.UNKNOWN_TECH
    if tech in civ["techs"]:
        return Reason.ALREADY_KNOWN
    if not techs.prereqs_met(civ["techs"], tech):
        return Reason.PREREQS_MISSING
    if not techs.gate_met(state, civ_id, techs.TECHS[tech].gate):
        return Reason.GATE_UNMET
    civ["research"]["tech"] = tech
    return None


def _entry(config: Config, settlement_id: str, building: str, mode: str, hint: str, tile: str) -> dict:
    return {"settlement": settlement_id, "building": building, "mode": mode, "hint": hint, "tile": tile,
            "cost": construction.queue_cost(config, building, mode),
            "ticks_left": construction.queue_ticks(config, building, mode), "started": False, "dropped": False}


def build(config: Config, state: dict, civ_id: str, settlement: str, building: str,
          tile: str | None = None, log: Log = None) -> Reason | None:
    """Queue a building. A tile holding one of the civ's own ruined or damaged buildings of the same
    type queues a rebuild or a repair; any other tile is a hint for a new building."""
    civ = state["civs"].get(civ_id)
    if civ is None:
        return Reason.UNKNOWN_CIV
    if building not in config.buildings:
        return Reason.UNKNOWN_BUILDING
    home = state["settlements"].get(settlement)
    if home is None or home["civ"] != civ_id:
        return Reason.NOT_OWN_SETTLEMENT
    if config.buildings[building]["tech"] not in civ["techs"]:
        return Reason.TECH_MISSING
    if len(civ["build_queue"]) >= config.build_queue_max:
        return Reason.QUEUE_FULL
    if tile is not None:
        try:
            parse_tile_key(tile)
        except ValueError:
            return Reason.BAD_TILE
        for sid in sorted(sid for sid, s in state["settlements"].items() if s["civ"] == civ_id):
            for existing in state["settlements"][sid]["buildings"]:
                if existing["tile"] != tile:
                    continue
                if existing["type"] != building or not (existing["ruin"] or existing["damaged"]):
                    return Reason.TILE_TAKEN
                if any(e["tile"] == tile for e in civ["build_queue"]):
                    return Reason.ALREADY_QUEUED
                mode = "rebuild" if existing["ruin"] else "repair"
                civ["build_queue"].append(_entry(config, sid, building, mode, "", tile))
                return None
    placed = construction.place(config, state, settlement, building, tile)
    if placed is None:
        return Reason.NO_TILE
    civ["build_queue"].append(_entry(config, placed[1], building, "new", tile or "", ""))
    return None


def allocate_workers(config: Config, state: dict, civ_id: str, allocation: dict, log: Log = None) -> Reason | None:
    """Set the standing worker split, in percent by line, adding up to at most 100."""
    if not isinstance(allocation, dict) or not set(allocation) <= set(rules.LINES):
        return Reason.BAD_ALLOCATION
    values = list(allocation.values())
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values) or sum(values) > 100:
        return Reason.BAD_ALLOCATION
    state["civs"][civ_id]["allocation"] = {line: allocation[line] for line in sorted(allocation)}
    return None


def train_unit(config: Config, state: dict, civ_id: str, settlement: str, unit_kind: str,
               log: Log = None) -> Reason | None:
    civ = state["civs"][civ_id]
    home = state["settlements"].get(settlement)
    if home is None or home["civ"] != civ_id:
        return Reason.NOT_OWN_SETTLEMENT
    spec = config.units.get(unit_kind)
    if spec is None:
        return Reason.UNKNOWN_UNIT_KIND
    if spec["tech"] and spec["tech"] not in civ["techs"]:
        return Reason.TECH_MISSING
    if spec["building"] and not any(b["type"] == spec["building"] and not b["ruin"] for b in home["buildings"]):
        return Reason.BUILDING_MISSING
    if any(civ["stocks"][res] < amount for res, amount in spec["cost"].items()):
        return Reason.CANNOT_AFFORD
    if home["pop"] <= spec["pop"]:  # a settlement always keeps at least one person (rules 21)
        return Reason.NOT_ENOUGH_PEOPLE
    units.spawn(config, state, civ_id, unit_kind, settlement, log)
    return None


def _own_unit(state: dict, civ_id: str, unit_id: str) -> Reason | None:
    """A foreign unit answers the same as a missing one, so a guessed id can't reveal another civ."""
    unit = state["units"].get(unit_id)
    if unit is None or unit["civ"] != civ_id:
        return Reason.UNKNOWN_UNIT
    return None


def move_unit(config: Config, state: dict, civ_id: str, unit: str, to: str, log: Log = None) -> Reason | None:
    """Send a trained unit towards a tile near ground the civ has seen. Replaces any old order;
    the unit's own tile cancels the order."""
    problem = _own_unit(state, civ_id, unit)
    if problem:
        return problem
    record = state["units"][unit]
    if not units.is_ready(state, record):
        return Reason.IN_TRAINING
    if not sight.near_known(state, civ_id, to, config.order_margin):
        return Reason.UNKNOWN_GROUND
    if to == record["tile"]:
        units.order(state, unit, to, [])
        return None
    path = units.route(config, state, record["tile"], to, believer=civ_id)
    if path is None:  # only ground the civ has seen can make a target unreachable
        return Reason.UNREACHABLE
    units.order(state, unit, to, path)
    return None


def disband_unit(config: Config, state: dict, civ_id: str, unit: str, log: Log = None) -> Reason | None:
    """People go home. Allowed on the home settlement's tile or anywhere in own territory."""
    problem = _own_unit(state, civ_id, unit)
    if problem:
        return problem
    record = state["units"][unit]
    owner = state["territory"].get(record["tile"])
    at_home = record["tile"] == state["settlements"][record["home"]]["tile"]
    if not at_home and (owner is None or state["settlements"][owner]["civ"] != civ_id):
        return Reason.NOT_IN_TERRITORY
    units.discharge(state, unit, log)
    return None


def met_civ(config: Config, state: dict, civ_id: str, name: object) -> str | None:
    """The id of the met civ a ruler named (by its name, any case), or None. A civ it hasn't met
    answers exactly like a made-up name, so a guess can't confirm that a civ exists."""
    if not isinstance(name, str):
        return None
    wanted = name.strip().lower()
    return next((other for other in sorted(state["civs"][civ_id]["met"])
                 if config.civ(other).name.lower() == wanted), None)


def set_note(config: Config, state: dict, civ_id: str, text: str, about: str | None = None,
             quote: bool | None = None, log: Log = None) -> Reason | None:
    """Add a line to the civ's journal, about a met civ if it names one. A quote is kept as a
    foreign claim of at most quote_chars; anything else is the civ's own inference, and may not
    copy a received message (memory.write refuses that)."""
    subject = ""
    if about is not None:
        subject = met_civ(config, state, civ_id, about)
        if subject is None:
            return Reason.UNKNOWN_CIV
    if quote:
        if not subject or len(text) > config.quote_chars:
            return Reason.BAD_NOTE
        source = memory.FOREIGN
    else:
        source = memory.OWN
    try:
        memory.write(config, state, civ_id, memory.JOURNAL, text, source, state["tick"], "decide", about=subject)
    except memory.NoteError:
        return Reason.BAD_NOTE
    return None


def send_message(config: Config, state: dict, civ_id: str, to: str, text: str, log: Log = None) -> Reason | None:
    """Hand a message to an engine courier (rules 7). Only to a met civ, at most
    messages_per_contact a tick, and only if a land path joins the two capitals."""
    receiver = met_civ(config, state, civ_id, to)
    if receiver is None:
        return Reason.UNKNOWN_CIV
    if messages.sent_this_tick(state, civ_id, receiver) >= config.messages_per_contact:
        return Reason.TOO_MANY_MESSAGES
    hardened = messages.harden(config, text)
    if not hardened:
        return Reason.EMPTY_MESSAGE
    arrives = messages.delivery_tick(config, state, civ_id, receiver)
    if arrives is None:
        return Reason.UNREACHABLE
    messages.dispatch(config, state, civ_id, receiver, hardened, arrives)
    return None


# ------------------------------------------------------------------ the table and the boundary


@dataclass(frozen=True)
class Arg:
    """One argument of an action. kind is "str", "int", "enum", "alloc" (percent by line), "tile"
    (relative "dx,dy"), "bool" or "civ" (a met civ's name; the schema lists only those). An enum
    miss gives its own reason, so a ruler learns which name was wrong rather than just that
    something was. A contact argument doesn't exist for a civ that has met no one."""

    kind: str
    required: bool = True
    max_len: int = 40
    low: int = 0
    high: int = 0
    choices: tuple[str, ...] = ()
    miss: Reason = Reason.BAD_ARGS
    contact: bool = False


@dataclass(frozen=True)
class ActionSpec:
    handler: Callable[..., Reason | None]
    args: Mapping[str, Arg]
    contact: bool = False  # only once the civ has met someone; before that it doesn't exist


def _enum(choices, miss: Reason) -> Arg:
    return Arg("enum", choices=tuple(sorted(choices)), miss=miss)


def action_table(config: Config) -> Mapping[str, ActionSpec]:
    """The one list of actions and their argument types. The tool schema is exported from it
    (fogline/schema.py), and dispatch() checks every action against it."""
    return {
        "allocate_workers": ActionSpec(allocate_workers, {"allocation": Arg("alloc")}),
        "set_research": ActionSpec(set_research, {"tech": _enum(techs.TECHS, Reason.UNKNOWN_TECH)}),
        "build": ActionSpec(build, {"settlement": Arg("str"),
                                    "building": _enum(config.buildings, Reason.UNKNOWN_BUILDING),
                                    "tile": Arg("tile", required=False)}),
        "train_unit": ActionSpec(train_unit, {"settlement": Arg("str"),
                                              "unit_kind": _enum(config.units, Reason.UNKNOWN_UNIT_KIND)}),
        "move_unit": ActionSpec(move_unit, {"unit": Arg("str"), "to": Arg("tile")}),
        "disband_unit": ActionSpec(disband_unit, {"unit": Arg("str")}),
        "set_note": ActionSpec(set_note, {"text": Arg("str", max_len=config.journal_chars),
                                          "about": Arg("civ", required=False, contact=True),
                                          "quote": Arg("bool", required=False, contact=True)}),
        "send_message": ActionSpec(send_message, {"to": Arg("civ"), "text": Arg("str", max_len=config.message_raw_chars)},
                                   contact=True),
    }


def to_map_tile(state: dict, civ_id: str, relative: object) -> str | None:
    """Turn a relative "dx,dy" from a ruler into a map tile, or None if it isn't one."""
    if not isinstance(relative, str):
        return None
    try:
        dx, dy = parse_tile_key(relative)
    except ValueError:
        return None
    ox, oy = parse_tile_key(state["civs"][civ_id]["origin"])
    return tile_key(ox + dx, oy + dy)


def _check_arg(arg: Arg, value: object) -> Reason | None:
    if arg.kind == "bool":
        if not isinstance(value, bool):
            return Reason.BAD_ARGS
    elif arg.kind == "civ":
        if not isinstance(value, str) or len(value) > arg.max_len:
            return Reason.BAD_ARGS
    elif arg.kind in ("str", "tile"):
        if not isinstance(value, str) or len(value) > arg.max_len:
            return Reason.BAD_ARGS
    elif arg.kind == "int":
        if not isinstance(value, int) or isinstance(value, bool) or not arg.low <= value <= arg.high:
            return Reason.BAD_ARGS
    elif arg.kind == "enum":
        if not isinstance(value, str):
            return Reason.BAD_ARGS
        if value not in arg.choices:
            return arg.miss
    elif arg.kind == "alloc":
        if not isinstance(value, dict):
            return Reason.BAD_ALLOCATION
    return None


def dispatch(config: Config, state: dict, civ_id: str, raw: object, log: Log = None) -> Reason | None:
    """Check one action from a ruler and run it. Never raises on what a ruler sends."""
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
        return Reason.MALFORMED
    spec = action_table(config).get(raw["kind"])
    alone = not state["civs"][civ_id]["met"]
    if spec is None or (alone and spec.contact):
        return Reason.UNKNOWN_ACTION  # before contact, a contact action answers like a made-up one
    given = {key: value for key, value in raw.items() if key != "kind"}
    if not set(given) <= {name for name, arg in spec.args.items() if not (alone and arg.contact)}:
        return Reason.BAD_ARGS
    args = {}
    for name, arg in spec.args.items():
        if name not in given:
            if not arg.required:
                args[name] = None
                continue
            return Reason.BAD_ARGS
        value = given[name]
        problem = _check_arg(arg, value)
        if problem:
            return problem
        if arg.kind == "tile":
            value = to_map_tile(state, civ_id, value)
            if value is None:
                return Reason.BAD_TILE
        args[name] = value
    return spec.handler(config, state, civ_id, **args, log=log)
