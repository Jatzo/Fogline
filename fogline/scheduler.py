"""Calls every woken civ's ruler at once, up to a cap, and hands the replies back in civ order
(PLAN section 10, "tick loop under concurrency").

The tick waits until every call has returned. Timeouts belong to the adapter, which records them
as an outcome (fogline/llm.py), so a replay never depends on how long a call took here.
"""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def call_all(calls: Mapping[str, Callable[[], Any]], cap: int) -> dict[str, Any]:
    """Run each call, at most cap at a time, and return {civ: result} in civ order. A call that
    raises (a replay that has no stored output, say) raises here once the others have finished."""
    order = sorted(calls)
    if cap <= 1 or len(order) <= 1:
        return {civ: calls[civ]() for civ in order}
    with ThreadPoolExecutor(max_workers=min(cap, len(order))) as pool:
        futures = {civ: pool.submit(calls[civ]) for civ in order}
        return {civ: futures[civ].result() for civ in order}
