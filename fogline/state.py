"""Canonical serialisation and hashing of world state.

State is plain data: dicts with string keys, lists, ints, strings, bools and None.
Floats are refused, because their text form and arithmetic are where cross-machine
differences creep in. Non-string keys are refused, because JSON turns them into strings
and a round trip would then change the hash.
"""

import hashlib
import json
from typing import Any


class StateError(ValueError):
    """Raised when state holds something that cannot be hashed the same way everywhere."""


def check_plain(value: Any, path: str = "state") -> None:
    """Walk the value and refuse floats, non-string keys and unknown types."""
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        raise StateError(f"float at {path}: state must be integer")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StateError(f"non-string key {key!r} at {path}")
            check_plain(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            check_plain(item, f"{path}[{index}]")
        return
    raise StateError(f"unsupported type {type(value).__name__} at {path}")


def canonical_json(value: Any) -> str:
    """Serialise with sorted keys and fixed separators so equal state gives equal text."""
    check_plain(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def state_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON, used by the determinism and snapshot tests."""
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def loads(text: str) -> Any:
    """Parse canonical JSON back into plain data, refusing floats on the way in."""

    def refuse_float(literal: str) -> Any:
        raise StateError(f"float {literal} in saved state")

    return json.loads(text, parse_float=refuse_float, parse_constant=refuse_float)


def tile_key(x: int, y: int) -> str:
    """Tiles are keyed as "x,y" strings so maps survive a JSON round trip."""
    return f"{x},{y}"


def parse_tile_key(key: str) -> tuple[int, int]:
    x_text, y_text = key.split(",")
    return int(x_text), int(y_text)


def record_event(state: dict, now: int, kind: str, civ_id: str, detail: str) -> None:
    """Add one entry to the world's event list, read by the viewer and the Chronicler."""
    state["events"].append({"tick": now, "kind": kind, "civ": civ_id, "detail": detail})
