"""A ruler's memory: a short journal and standing strategy notes (PLAN section 8).

write() is the only way into civ["memory"]. Every entry carries its source, own_inference or
foreign_claim, and where it came from (tick and step), so a poisoned message can't turn into a
note the civ trusts as its own. Rulers write their own journal through the set_note action and
rewrite their strategy in the reflection step; foreign claims arrive with messages in Phase 3.
"""

from difflib import SequenceMatcher

from fogline.config import Config

JOURNAL, STRATEGY = "journal", "strategy"
OWN, FOREIGN = "own_inference", "foreign_claim"
SOURCES = (OWN, FOREIGN)


class NoteError(ValueError):
    """Raised when a write breaks the memory rules: unknown kind or source, not plain text, too long."""


def empty() -> dict:
    return {JOURNAL: [], STRATEGY: {"text": "", "tick": -1, "step": ""}}


def _plain(text: object, limit: int) -> str:
    """Printable text with newlines allowed and nothing else: no control characters, no markup
    tricks hidden in them, and no more than limit characters."""
    if not isinstance(text, str):
        raise NoteError("a note must be text")
    if len(text) > limit:
        raise NoteError(f"a note may be at most {limit} characters")
    if any(not (char.isprintable() or char == "\n") for char in text):
        raise NoteError("a note may hold only printable text and newlines")
    return text


def _copies_a_message(config: Config, state: dict, civ_id: str, text: str) -> bool:
    """Whether text shares more than quote_chars running characters with a message the civ has
    received, which would launder a foreign claim into the civ's own notes."""
    for received in state["civs"][civ_id]["inbox"]:
        plain = received["plain"]
        mine, theirs = text.lower(), plain.lower()  # lowering can lengthen a string ("İ" becomes 2 characters)
        match = SequenceMatcher(None, mine, theirs, autojunk=False).find_longest_match(0, len(mine), 0, len(theirs))
        if match.size > config.quote_chars:
            return True
    return False


def write(config: Config, state: dict, civ_id: str, kind: str, text: object, source: str, tick: int,
          step: str, about: str = "") -> None:
    """Add a journal entry (oldest dropped past the cap) or replace the strategy notes. about is
    the met civ a journal entry concerns, if any."""
    if source not in SOURCES:
        raise NoteError(f"unknown source {source!r}")
    if source == OWN and isinstance(text, str) and _copies_a_message(config, state, civ_id, text):
        raise NoteError("an own note may not copy a received message; keep it as a quote")
    memory = state["civs"][civ_id]["memory"]
    if kind == JOURNAL:
        entry = {"text": _plain(text, config.journal_chars), "source": source, "tick": tick, "step": step,
                 "about": about}
        memory[JOURNAL] = (memory[JOURNAL] + [entry])[-config.journal_entries:]
    elif kind == STRATEGY:
        if source != OWN:
            raise NoteError("strategy notes are the civ's own; a foreign claim can't become one")
        memory[STRATEGY] = {"text": _plain(text, config.strategy_chars), "tick": tick, "step": step}
    else:
        raise NoteError(f"unknown memory kind {kind!r}")


def view(state: dict, civ_id: str) -> tuple[list[dict], str]:
    """The journal and strategy as a ruler sees them."""
    memory = state["civs"][civ_id]["memory"]
    journal = [{"tick": e["tick"], "text": e["text"], "source": e["source"], "about": e.get("about", "")}
               for e in memory[JOURNAL]]
    return journal, memory[STRATEGY]["text"]
