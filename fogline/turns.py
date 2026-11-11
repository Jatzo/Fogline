"""Step 1 of the tick: wake and decide (docs/rules.md sections 1 and 16, ADR 0003).

A ruler is a decider: a function from an observation (fogline/observation.py, the only view of
state a ruler gets) and its own scratch memory to a Reply. A scripted bot and an LLM ruler plug in
the same way and never touch state; an LLM ruler ignores the scratch memory. Wakes are read off state["events"] through a cursor
per civ and one table, EVENT_TRIGGERS, so no other module has to wake anyone.

This module is the only writer of civ["turn"], civ["reorders"] and civ["bot_memory"].
"""

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from fogline import actions, observation, schema
from fogline.actions import Reason
from fogline.config import RESOURCES, Config
from fogline.state import StateError, check_plain, record_event


class Trigger(StrEnum):
    """The whole wake list (PLAN section 10). The first five have no source until Phase 3 or 5."""

    MESSAGE_RECEIVED = "message_received"
    OFFER_RECEIVED = "offer_received"
    OFFER_EXPIRING = "offer_expiring"
    TREATY_PROPOSED = "treaty_proposed"
    ATTACK = "attack"
    UNIT_ARRIVED = "unit_arrived"
    UNIT_IDLE = "unit_idle"
    BUILD_DONE = "build_done"
    STOCK_BELOW_THRESHOLD = "stock_below_threshold"
    FOREIGN_UNIT_SIGHTED = "foreign_unit_sighted"
    CONTACT = "contact"
    TECH_UNLOCKED = "tech_unlocked"


ALWAYS_ON = frozenset({Trigger.ATTACK, Trigger.CONTACT, Trigger.TREATY_PROPOSED, Trigger.OFFER_EXPIRING})

# Event kind in state["events"] -> the trigger it raises for that event's civ. The only place
# this mapping lives; Phases 3 and 5 add rows here and wake nobody anywhere else.
EVENT_TRIGGERS: Mapping[str, Trigger] = {
    "built": Trigger.BUILD_DONE, "tech": Trigger.TECH_UNLOCKED, "contact": Trigger.CONTACT,
    "sighted": Trigger.FOREIGN_UNIT_SIGHTED, "arrived": Trigger.UNIT_ARRIVED, "idle": Trigger.UNIT_IDLE,
    "below": Trigger.STOCK_BELOW_THRESHOLD,
}


class Reply(TypedDict, total=False):
    """What a ruler returns: plain data, checked here, never trusted."""

    actions: list
    end_turn: dict  # {"next_wake": {"ticks": 1..8, "triggers": [...]}, "reorders": [...] or None}
    memory: dict  # scripted bots only


Decider = Callable[[dict, dict], Reply]  # (observation, scratch memory) -> reply


@dataclass(frozen=True)
class TurnRecord:
    """One decision, kept by the runner outside the hashed state, keyed (tick, civ, step)."""

    tick: int
    civ: str
    step: str
    observation: dict | None
    reply: Any
    rejections: tuple[dict, ...]

    def as_record(self) -> dict:
        return {"tick": self.tick, "civ": self.civ, "step": self.step, "observation": self.observation,
                "reply": self.reply,
                "rejections": list(self.rejections)}


# ------------------------------------------------------------------ wakes


def _note_thresholds(state: dict, civ_id: str, now: int) -> None:
    """Record a "below" event when a reorder rule's stock first drops under its threshold."""
    civ = state["civs"][civ_id]
    below = {r["stock"] for r in civ["reorders"] if civ["stocks"][r["stock"]] < r["below"]}
    for stock in sorted(below - set(civ["turn"]["below"])):
        record_event(state, now, "below", civ_id, stock)
    civ["turn"]["below"] = sorted(below)


def _due(config: Config, state: dict, civ_id: str, now: int) -> list[dict]:
    """The reasons this civ wakes now, or [] if it sleeps. Reads state only."""
    turn = state["civs"][civ_id]["turn"]
    raised = [{"trigger": EVENT_TRIGGERS[e["kind"]], "detail": e["detail"]}
              for e in state["events"][turn["cursor"]:] if e["civ"] == civ_id and e["kind"] in EVENT_TRIGGERS]
    wanted = set(turn["triggers"]) | ALWAYS_ON
    timer = now >= turn["wake_at"]
    heartbeat = now - turn["last_woke"] >= config.heartbeat_ticks
    if not (timer or heartbeat or any(r["trigger"] in wanted for r in raised)):
        return []
    if timer:
        raised.append({"trigger": "timer", "detail": ""})
    if heartbeat:
        raised.append({"trigger": "heartbeat", "detail": ""})
    return raised


def _parse_end_turn(config: Config, raw: object) -> tuple[int, list[str], list[dict] | None] | Reason:
    """Turn a ruler's end_turn into (ticks, triggers, reorders), or a Reason. Never raises."""
    if not isinstance(raw, dict) or not set(raw) <= {"next_wake", "reorders"}:
        return Reason.BAD_END_TURN
    wake = raw.get("next_wake")
    if not isinstance(wake, dict) or not set(wake) <= {"ticks", "triggers"}:
        return Reason.BAD_END_TURN
    ticks = wake.get("ticks")
    if not isinstance(ticks, int) or isinstance(ticks, bool) or not 1 <= ticks <= config.max_wake_ticks:
        return Reason.BAD_END_TURN
    triggers = wake.get("triggers", [])
    valid = {t.value for t in Trigger}
    if not isinstance(triggers, list) or any(not isinstance(t, str) or t not in valid for t in triggers):
        return Reason.BAD_END_TURN
    reorders = raw.get("reorders")
    if reorders is not None:
        if not isinstance(reorders, list) or len(reorders) > config.max_reorders:
            return Reason.BAD_END_TURN
        for rule in reorders:
            if (not isinstance(rule, dict) or set(rule) != {"stock", "below", "workers"}
                    or rule["stock"] not in RESOURCES
                    or not isinstance(rule["below"], int) or isinstance(rule["below"], bool) or rule["below"] < 0
                    or not isinstance(rule["workers"], int) or isinstance(rule["workers"], bool)
                    or rule["workers"] < 1):
                return Reason.BAD_END_TURN
        reorders = [{"stock": r["stock"], "below": r["below"], "workers": r["workers"]} for r in reorders]
    return ticks, sorted(set(triggers)), reorders


def _apply(config: Config, state: dict, civ_id: str, seen: dict | None, reply: object,
           log: list | None) -> TurnRecord:
    """Apply one reply. No reply (no decider, or a Phase 2 timeout) is an empty turn."""
    now = state["tick"]
    civ = state["civs"][civ_id]
    turn = civ["turn"]
    rejections: list[dict] = []

    def reject(index: int, kind: object, reason: Reason) -> None:
        rejections.append({"index": index, "kind": kind if isinstance(kind, str) else "", "reason": reason.value})

    raw_actions: list = []
    malformed = False  # a garbled reply counts as a wholly invalid turn, so it can't dodge the skip
    if reply is None:
        parsed: tuple | Reason = (config.heartbeat_ticks, [], None)
    elif not isinstance(reply, dict) or schema.depth(reply) > schema.MAX_DEPTH:
        malformed = True
        reject(-1, "", Reason.MALFORMED)
        parsed = Reason.BAD_END_TURN
    else:
        if isinstance(reply.get("actions", []), list):
            raw_actions = reply.get("actions", [])
        else:
            malformed = True
            reject(-1, "actions", Reason.MALFORMED)
        for index, raw in enumerate(raw_actions):
            kind = raw.get("kind") if isinstance(raw, dict) else ""
            if index >= config.max_actions_per_turn:
                reject(index, kind, Reason.OVER_ACTION_CAP)
                continue
            reason = actions.dispatch(config, state, civ_id, raw, log)
            if reason is not None:
                reject(index, kind, reason)
        parsed = _parse_end_turn(config, reply.get("end_turn"))
        if "memory" in reply:
            try:
                check_plain(reply["memory"])
                if not isinstance(reply["memory"], dict):
                    raise StateError("memory must be a dict")
                civ["bot_memory"] = copy.deepcopy(reply["memory"])
            except StateError:
                reject(-1, "memory", Reason.BAD_MEMORY)

    if isinstance(parsed, Reason):
        reject(-1, "end_turn", parsed)
        parsed = (1, [], None)  # ask a broken ruler again next tick
    ticks, triggers, reorders = parsed
    turn["wake_at"] = now + ticks
    turn["triggers"] = triggers
    if reorders is not None:
        civ["reorders"] = reorders

    acted = sum(1 for r in rejections if r["index"] >= 0)
    if malformed or (raw_actions and acted == len(raw_actions)):
        turn["invalid_streak"] += 1
        if turn["invalid_streak"] >= config.invalid_turns_before_skip:
            turn["skip_next"] = True
            turn["invalid_streak"] = 0
    else:
        turn["invalid_streak"] = 0  # an empty turn resets the streak too (rules 21)
    turn["rejections"] = rejections
    too_deep = isinstance(reply, (dict, list)) and schema.depth(reply) > schema.MAX_DEPTH
    kept = "(reply nested too deep to keep)" if too_deep else copy.deepcopy(reply)
    return TurnRecord(now, civ_id, "decide", seen, kept, tuple(rejections))


def step(config: Config, state: dict, deciders: Mapping[str, Decider] | None, log: list | None) -> list[TurnRecord]:
    """Step 1. Every due civ's observation is built before any reply is applied, then the deciders are
    called (a plain loop now; Phase 2 makes this the concurrent part), then replies are applied in
    civ id order. The cursor moves when a decider is called, so anything recorded later waits for
    the next wake. A skipped turn leaves the cursor alone, so its triggers are kept."""
    now = state["tick"]
    deciders = deciders or {}
    civ_ids = sorted(state["civs"])
    for civ_id in civ_ids:
        _note_thresholds(state, civ_id, now)
    due = {civ_id: why for civ_id in civ_ids if (why := _due(config, state, civ_id, now))}

    records: list[TurnRecord] = []
    seen: dict[str, dict | None] = {}
    for civ_id in sorted(due):
        turn = state["civs"][civ_id]["turn"]
        if turn["skip_next"]:
            turn["skip_next"] = False
            turn["wake_at"] = now + 1
            record_event(state, now, "turn_skipped", civ_id, "")
            records.append(TurnRecord(now, civ_id, "decide", None, None, ()))
            continue
        seen[civ_id] = observation.observe(config, state, civ_id, due[civ_id]) if civ_id in deciders else None
        turn["last_woke"] = now
    for civ_id in seen:
        turn = state["civs"][civ_id]["turn"]
        turn["cursor"] = len(state["events"])
        turn["seen_stocks"] = dict(state["civs"][civ_id]["stocks"])  # stock_changes count from here
    replies = {civ_id: (deciders[civ_id](copy.deepcopy(seen[civ_id]), copy.deepcopy(state["civs"][civ_id]["bot_memory"]))
                        if civ_id in deciders else None) for civ_id in seen}
    for civ_id in sorted(seen):
        records.append(_apply(config, state, civ_id, seen[civ_id], replies[civ_id], log))
    return sorted(records, key=lambda r: r.civ)
