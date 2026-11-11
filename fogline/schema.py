"""The reply a ruler sends, as text, and the schema it is told to follow (PLAN section 5).

validate_reply() is the first thing an LLM's raw text meets: a size cap, a JSON parse and a depth
limit, then the top-level shape. Everything it passes still goes through turns._apply and
actions.dispatch, which check each action and end_turn. json_schema() is exported from
actions.action_table(), so the schema a ruler reads and the checks it meets come from one table.
"""

import json
from typing import Any

from fogline import rules
from fogline.actions import Arg, Reason, action_table
from fogline.config import RESOURCES, Config

MAX_REPLY_CHARS = 20_000
MAX_DEPTH = 8  # a real reply nests about 4 deep: reply, actions, action, allocation
REPLY_KEYS = frozenset({"actions", "end_turn"})


def depth(value: Any) -> int:
    """How deeply value nests, counted without recursion so a hostile reply can't blow the stack."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, level = stack.pop()
        deepest = max(deepest, level)
        if level > MAX_DEPTH:
            return level
        if isinstance(item, dict):
            stack.extend((child, level + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, level + 1) for child in item)
    return deepest


def text_depth(text: str) -> int:
    """How deeply brackets nest in JSON text, ignoring brackets inside strings. Read before
    parsing, so the parser never meets deep input: whether json.loads survives a very deep text
    depends on the platform's recursion limit, and a reply must get the same answer everywhere."""
    deepest = level = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            level += 1
            deepest = max(deepest, level)
        elif char in "]}":
            level -= 1
    return deepest


def validate_reply(text: object) -> tuple[dict | None, list[dict]]:
    """Turn a ruler's raw text into a reply dict, or None with the rejection that explains why.
    Never raises on what a ruler sends."""

    def refuse(detail: str) -> tuple[None, list[dict]]:
        return None, [{"index": -1, "kind": detail, "reason": Reason.UNPARSEABLE_REPLY.value}]

    if not isinstance(text, str):
        return refuse("not_text")
    if len(text) > MAX_REPLY_CHARS:
        return refuse("too_long")
    if text_depth(text) > MAX_DEPTH:
        return refuse("too_deep")
    try:
        reply = json.loads(text)
    except ValueError:
        return refuse("not_json")
    if not isinstance(reply, dict) or not set(reply) <= REPLY_KEYS:
        return None, [{"index": -1, "kind": "reply", "reason": Reason.MALFORMED.value}]
    return reply, []


def validate_reflection(text: object) -> tuple[str | None, list[dict]]:
    """A reflection's raw text: exactly {"strategy": "..."}. The length is checked when it is
    written (memory.write), so a long one comes back as bad_note."""

    def refuse(detail: str, reason: Reason = Reason.UNPARSEABLE_REPLY) -> tuple[None, list[dict]]:
        return None, [{"index": -1, "kind": detail, "reason": reason.value}]

    if not isinstance(text, str):
        return refuse("not_text")
    if len(text) > MAX_REPLY_CHARS:
        return refuse("too_long")
    if text_depth(text) > MAX_DEPTH:
        return refuse("too_deep")
    try:
        reply = json.loads(text)
    except ValueError:
        return refuse("not_json")
    if not isinstance(reply, dict) or set(reply) != {"strategy"} or not isinstance(reply["strategy"], str):
        return refuse("reflection", Reason.MALFORMED)
    return reply["strategy"], []


def _arg_schema(arg: Arg) -> dict:
    if arg.kind == "str":
        return {"type": "string", "maxLength": arg.max_len}
    if arg.kind == "tile":
        return {"type": "string", "pattern": r"^-?\d+,-?\d+$", "description": "tile as dx,dy from your capital"}
    if arg.kind == "int":
        return {"type": "integer", "minimum": arg.low, "maximum": arg.high}
    if arg.kind == "enum":
        return {"type": "string", "enum": list(arg.choices)}
    if arg.kind == "alloc":
        return {"type": "object", "additionalProperties": False,
                "properties": {line: {"type": "integer", "minimum": 0, "maximum": 100} for line in rules.LINES},
                "description": "percent of workers by line, adding up to at most 100"}
    raise ValueError(f"no schema for argument kind {arg.kind!r}")


def json_schema(config: Config, met: bool = False) -> dict:
    """The JSON Schema of a reply, built from the action table and the end_turn limits. Before a
    civ has met anyone it lists only the wake triggers a civ alone can use."""
    variants = []
    for kind, spec in sorted(action_table(config).items()):
        properties = {"kind": {"const": kind}} | {name: _arg_schema(arg) for name, arg in spec.args.items()}
        required = ["kind"] + [name for name, arg in spec.args.items() if arg.required]
        variants.append({"type": "object", "properties": properties, "required": required,
                         "additionalProperties": False})
    from fogline.turns import CONTACT_TRIGGERS, OWN_TRIGGERS  # turns imports this module, so this waits
    triggers = OWN_TRIGGERS + (CONTACT_TRIGGERS if met else ())
    reorder = {"type": "object", "additionalProperties": False, "required": ["stock", "below", "workers"],
               "properties": {"stock": {"type": "string", "enum": sorted(RESOURCES)},
                              "below": {"type": "integer", "minimum": 0},
                              "workers": {"type": "integer", "minimum": 1}}}
    end_turn = {"type": "object", "additionalProperties": False, "required": ["next_wake"], "properties": {
        "next_wake": {"type": "object", "additionalProperties": False, "required": ["ticks"], "properties": {
            "ticks": {"type": "integer", "minimum": 1, "maximum": config.max_wake_ticks},
            "triggers": {"type": "array", "items": {"type": "string", "enum": sorted(t.value for t in triggers)}}}},
        "reorders": {"type": "array", "maxItems": config.max_reorders, "items": reorder}}}
    return {"type": "object", "additionalProperties": False, "properties": {
        "actions": {"type": "array", "maxItems": config.max_actions_per_turn, "items": {"oneOf": variants}},
        "end_turn": end_turn}}
