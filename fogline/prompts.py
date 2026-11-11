"""The text a live ruler reads: one system prompt per civ, and the observation as the message.

The system prompt is prompts/ruler.md with the reply schema (exported from the action table) and
the civ's own culture (prompts/cultures/<civ>.md) put in. Nothing here may mention another civ,
how many there are, or the size of the map; tests/test_prompts.py checks every rendered prompt.
"""

import json
from pathlib import Path

from fogline import schema
from fogline.config import Config
from fogline.state import canonical_json

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def has_culture(civ_id: str) -> bool:
    return (PROMPTS / "cultures" / f"{civ_id}.md").exists()


def system_prompt(config: Config, civ_id: str) -> str:
    if not has_culture(civ_id):
        raise ValueError(f"no culture prompt for {civ_id} (prompts/cultures/{civ_id}.md)")
    ruler = (PROMPTS / "ruler.md").read_text(encoding="utf-8")
    culture = (PROMPTS / "cultures" / f"{civ_id}.md").read_text(encoding="utf-8").strip()
    return (ruler.replace("{{SCHEMA}}", json.dumps(schema.json_schema(config), sort_keys=True))
            .replace("{{CULTURE}}", culture))


def user_message(payload: dict) -> str:
    """The observation (or reflection request) exactly as sent."""
    return canonical_json(payload)
