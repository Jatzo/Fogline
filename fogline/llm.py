"""The LLM adapter: how a ruler's observation becomes reply text, and how that text is kept
(PLAN sections 10 and 11, ADR 0007).

Every adapter has one method, call(key, observation) -> Outcome, where key is (tick, civ, step).
- MockAdapter wraps scripted deciders and speaks JSON text, so the parse path always runs.
- LiveAdapter runs `claude -p` on the operator's plan login. Never used in tests.
- Recorder wraps either and keeps one row per call: status, raw text and the observation's hash.
- ReplayAdapter answers from those rows and never calls or times anything, so a replay applies
  exactly what happened, timeouts included. It fails loudly on a missing row or on an
  observation that differs from the one the row was made for.
make_ruler() turns an adapter into a decider for one civ.
"""

import copy
import json
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fogline import prompts, schema
from fogline.state import canonical_json, state_hash
from fogline.turns import Decider, Refused

OK, TIMEOUT, ERROR = "ok", "timeout", "error"
MODEL = "claude-haiku-5-5"  # every ruler, by project decision (PLAN section 1)
Key = tuple[int, str, str]  # (tick, civ, step)


@dataclass(frozen=True)
class Outcome:
    status: str  # ok, timeout or error
    raw: str  # the reply text for ok; a short note for timeout or error
    usage: dict | None = None  # token counts and cost for a live call (USAGE_FIELDS only)


# The numbers kept from a live call's output envelope. The envelope is untrusted and the repo is
# public, so nothing else from it is stored (session ids, paths, account details).
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _usage(envelope: dict) -> dict | None:
    counts = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    kept = {k: counts[k] for k in USAGE_FIELDS
            if isinstance(counts.get(k), int) and not isinstance(counts.get(k), bool)}
    cost = envelope.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        kept["total_cost_usd"] = cost
    return kept or None


class Adapter(Protocol):
    def call(self, key: Key, observation: dict) -> Outcome: ...


class LiveFailure(RuntimeError):
    """Raised by the runner when live calls keep failing, so a broken CLI can't play a whole game
    of empty turns (fogline/run.py)."""


class ReplayError(RuntimeError):
    """Raised when a replay has no stored output for a call, or the call's observation changed."""


class MockAdapter:
    """Scripted deciders behind the text interface. Their scratch memory stays here, on the
    adapter's side, the way an LLM's own context would: it never enters state or a reply."""

    def __init__(self, deciders: Mapping[str, Decider]):
        self.deciders = dict(deciders)
        self.memory: dict[str, dict] = {civ: {} for civ in self.deciders}

    def call(self, key: Key, observation: dict) -> Outcome:
        _, civ, step = key
        if step == "reflect":  # a plain summary, so the reflection path runs in every mock game
            seen = observation["observation"]
            text = (f"Tick {seen['tick']}: {seen['population']} people, stability {seen['stability']}, "
                    f"researching {seen['research']['tech'] or 'nothing'}.")
            return Outcome(OK, canonical_json({"strategy": text}))
        reply = dict(self.deciders[civ](copy.deepcopy(observation), copy.deepcopy(self.memory[civ])) or {})
        self.memory[civ] = reply.pop("memory", self.memory[civ])
        return Outcome(OK, canonical_json(reply))


class LiveAdapter:
    """One `claude -p` subprocess per call, on the operator's plan login (no API key). It runs in
    safe mode (no CLAUDE.md, hooks, skills, plugins or user settings) in an empty folder, with no
    tools, no MCP servers and no saved session. Without safe mode, Claude Code builds the
    operator's own instructions and hook output into every call (ADR 0007)."""

    def __init__(self, prompt_for: Callable[[str, bool], str], model: str = MODEL, timeout: float = 90.0,
                 command: tuple[str, ...] = ("claude",)):
        """prompt_for(civ, met) gives the civ's system prompt; it changes once the civ meets someone."""
        self.prompt_for, self.model, self.timeout, self.command = prompt_for, model, timeout, command

    def call(self, key: Key, observation: dict) -> Outcome:
        argv = [*self.command, "-p", "--safe-mode", "--model", self.model, "--output-format", "json",
                "--system-prompt", self.prompt_for(key[1], prompts.has_met(observation)), "--tools", "",
                "--strict-mcp-config",
                "--no-session-persistence"]
        with tempfile.TemporaryDirectory() as empty:
            try:
                done = subprocess.run(argv, input=prompts.user_message(observation), capture_output=True, text=True,
                                      encoding="utf-8", timeout=self.timeout, cwd=empty, check=False)
            except subprocess.TimeoutExpired:
                return Outcome(TIMEOUT, f"no reply in {self.timeout:g} s")
            except OSError as error:
                return Outcome(ERROR, f"could not start {self.command[0]}: {error}"[:500])
        if done.returncode != 0:
            return Outcome(ERROR, f"exit {done.returncode}: {done.stderr.strip()}"[:500])
        try:
            envelope = json.loads(done.stdout)
        except ValueError:
            return Outcome(ERROR, f"output was not JSON: {done.stdout[:200]}")
        if not isinstance(envelope, dict) or envelope.get("is_error") or not isinstance(envelope.get("result"), str):
            return Outcome(ERROR, f"no result in output: {done.stdout[:300]}")
        return Outcome(OK, envelope["result"], _usage(envelope))


class Recorder:
    """Wraps an adapter and keeps every outcome, in call order, optionally appending to a file."""

    def __init__(self, inner: Adapter, path: Path | None = None):
        self.inner, self.path, self.rows = inner, path, []
        self.lock = threading.Lock()  # rulers are called in parallel; one row is written at a time

    def call(self, key: Key, observation: dict) -> Outcome:
        outcome = self.inner.call(key, observation)
        tick, civ, step = key
        row = {"tick": tick, "civ": civ, "step": step, "status": outcome.status, "raw": outcome.raw,
               "obs_hash": state_hash(observation), "usage": outcome.usage}
        with self.lock:
            self.rows.append(row)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        return outcome

    def tokens(self) -> dict[str, dict[str, float]]:
        """Token counts and cost so far per civ, from the rows that carry usage (live calls)."""
        totals: dict[str, dict[str, float]] = {}
        for row in self.rows:
            for key, value in (row.get("usage") or {}).items():
                civ = totals.setdefault(row["civ"], {})
                civ[key] = civ.get(key, 0) + value
        return totals

    def usage(self) -> dict[str, dict[str, int]]:
        """Calls so far per civ, by status."""
        counts: dict[str, dict[str, int]] = {}
        for row in self.rows:
            by_status = counts.setdefault(row["civ"], {})
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        return {civ: dict(sorted(by_status.items())) for civ, by_status in sorted(counts.items())}


class ReplayAdapter:
    def __init__(self, rows: list[dict]):
        self.rows: dict[Key, dict] = {}
        for row in rows:
            key = (row["tick"], row["civ"], row["step"])
            if key in self.rows:
                raise ReplayError(f"two stored outputs for {key}")
            self.rows[key] = row

    def call(self, key: Key, observation: dict) -> Outcome:
        row = self.rows.get(key)
        if row is None:
            raise ReplayError(f"no stored output for {key}")
        if row["obs_hash"] != state_hash(observation):
            raise ReplayError(f"the observation for {key} differs from the one the stored output answered")
        return Outcome(row["status"], row["raw"])


def load_outputs(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def make_ruler(adapter: Adapter, civ_id: str) -> Decider:
    """A decider that asks the adapter. A timeout or error is an empty turn; text that fails
    schema.validate_reply is refused with its reason, which the civ sees next turn. The decider's
    reflect() asks for new strategy notes the same way (turns.reflect calls it)."""

    def decide(observation: dict, scratch: dict):
        outcome = adapter.call((observation["tick"], civ_id, "decide"), observation)
        if outcome.status != OK:
            return None
        reply, rejections = schema.validate_reply(outcome.raw)
        return reply if reply is not None else Refused(tuple(rejections))

    def reflect(observation: dict):
        outcome = adapter.call((observation["tick"], civ_id, "reflect"), {"step": "reflect", "observation": observation})
        if outcome.status != OK:
            return None
        text, rejections = schema.validate_reflection(outcome.raw)
        return text if text is not None else Refused(tuple(rejections))

    decide.reflect = reflect  # type: ignore[attr-defined]
    return decide
