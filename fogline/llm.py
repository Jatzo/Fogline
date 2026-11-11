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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fogline import schema
from fogline.state import canonical_json, state_hash
from fogline.turns import Decider, Refused

OK, TIMEOUT, ERROR = "ok", "timeout", "error"
Key = tuple[int, str, str]  # (tick, civ, step)


@dataclass(frozen=True)
class Outcome:
    status: str  # ok, timeout or error
    raw: str  # the reply text for ok; a short note for timeout or error


class Adapter(Protocol):
    def call(self, key: Key, observation: dict) -> Outcome: ...


class ReplayError(RuntimeError):
    """Raised when a replay has no stored output for a call, or the call's observation changed."""


class MockAdapter:
    """Scripted deciders behind the text interface. Their scratch memory stays here, on the
    adapter's side, the way an LLM's own context would: it never enters state or a reply."""

    def __init__(self, deciders: Mapping[str, Decider]):
        self.deciders = dict(deciders)
        self.memory: dict[str, dict] = {civ: {} for civ in self.deciders}

    def call(self, key: Key, observation: dict) -> Outcome:
        _, civ, _ = key
        reply = dict(self.deciders[civ](copy.deepcopy(observation), copy.deepcopy(self.memory[civ])) or {})
        self.memory[civ] = reply.pop("memory", self.memory[civ])
        return Outcome(OK, canonical_json(reply))


class LiveAdapter:
    """One `claude -p` subprocess per call, on the operator's plan login (no API key). It runs in
    safe mode (no CLAUDE.md, hooks, skills, plugins or user settings) in an empty folder, with no
    tools, no MCP servers and no saved session. Without safe mode, Claude Code builds the
    operator's own instructions and hook output into every call (ADR 0007)."""

    def __init__(self, system_prompt: str, model: str = "claude-haiku-5-5", timeout: float = 90.0,
                 command: tuple[str, ...] = ("claude",)):
        self.system_prompt, self.model, self.timeout, self.command = system_prompt, model, timeout, command

    def call(self, key: Key, observation: dict) -> Outcome:
        argv = [*self.command, "-p", "--safe-mode", "--model", self.model, "--output-format", "json",
                "--system-prompt", self.system_prompt, "--tools", "", "--strict-mcp-config",
                "--no-session-persistence"]
        with tempfile.TemporaryDirectory() as empty:
            try:
                done = subprocess.run(argv, input=canonical_json(observation), capture_output=True, text=True,
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
        return Outcome(OK, envelope["result"])


class Recorder:
    """Wraps an adapter and keeps every outcome, in call order, optionally appending to a file."""

    def __init__(self, inner: Adapter, path: Path | None = None):
        self.inner, self.path, self.rows = inner, path, []

    def call(self, key: Key, observation: dict) -> Outcome:
        outcome = self.inner.call(key, observation)
        tick, civ, step = key
        row = {"tick": tick, "civ": civ, "step": step, "status": outcome.status, "raw": outcome.raw,
               "obs_hash": state_hash(observation)}
        self.rows.append(row)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        return outcome


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


def make_ruler(adapter: Adapter, civ_id: str, step: str = "decide") -> Decider:
    """A decider that asks the adapter. A timeout or error is an empty turn; text that fails
    schema.validate_reply is refused with its reason, which the civ sees next turn."""

    def decide(observation: dict, scratch: dict):
        outcome = adapter.call((observation["tick"], civ_id, step), observation)
        if outcome.status != OK:
            return None
        reply, rejections = schema.validate_reply(outcome.raw)
        return reply if reply is not None else Refused(tuple(rejections))

    return decide
