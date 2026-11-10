"""Seeded random streams.

Every draw site asks for a fresh stream keyed by (run seed, system, tick, civ, purpose).
No stream carries state from one draw site to the next, so a change in one civ's actions
can never shift the numbers another civ or another system draws (PLAN.md section 11).

Only randrange, randint, choice and shuffle on integers are used: these are built on
getrandbits and have been stable across CPython versions. random() returns floats and is not used.
"""

import hashlib
import random

SYSTEMS = frozenset({"worldgen", "combat", "unrest", "rebellion", "events"})
WORLD = "world"


def stream(seed: int, system: str, tick: int, civ: str, purpose: str) -> random.Random:
    """Return a new Random seeded from SHA-256 of the full key."""
    if system not in SYSTEMS:
        raise ValueError(f"unknown rng system {system!r}")
    if not purpose:
        raise ValueError("every draw site needs a purpose key")
    if "|" in civ or "|" in purpose:
        raise ValueError("civ and purpose may not contain '|', the key separator")
    key = f"{seed}|{system}|{tick}|{civ}|{purpose}".encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(key).digest(), "big"))


def chance(rng: random.Random, per_mille_rate: int) -> bool:
    """True with probability per_mille_rate / 1000, using an integer draw."""
    return rng.randrange(1000) < per_mille_rate
