"""Save and restore world state (PLAN section 11).

A snapshot is the canonical JSON of the whole state, gzipped with a fixed timestamp so the
same state always gives the same bytes. Restoring and continuing must reach the same state
hash as a run that never stopped; the resume test holds that.
"""

import gzip
import json
from pathlib import Path
from typing import Any

from fogline.state import canonical_json, loads


def save(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(state).encode("ascii")
    # An empty filename and a zero time keep the local path and the clock out of the gzip header,
    # so a snapshot holds nothing but the state and can be shared as it is.
    with open(path, "wb") as handle, gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as packed:
        packed.write(data)


def load(path: Path) -> dict:
    with gzip.open(path, "rb") as packed:
        return loads(packed.read().decode("ascii"))


def append_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append records as JSON lines (the ledger log and the turn records, kept outside the hash)."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="ascii") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
