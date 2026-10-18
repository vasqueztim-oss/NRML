"""Loading persona prompts and calling Claude with them."""

import json
import os
from pathlib import Path
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from nrml import schemas

ROOT = Path(__file__).resolve().parent.parent
PERSONA_DIR = ROOT / "personas"
CHARTER_DIR = ROOT / "charter"

MODEL = os.environ.get("NRML_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("NRML_EFFORT", "high")
MAX_TOKENS = 64000

# Which charter files each persona's prompt says are appended below it.
CHARTER_FILES = {
    "wire_desk": ["rules.md"],
    "fact_checker": ["rules.md"],
    "assignment_editor": ["rules.md", "where_we_stand.md"],
    "beat_reporter": ["rules.md", "where_we_stand.md"],
    "standards_editor": ["rules.md", "where_we_stand.md"],
    "policy_desk": ["rules.md", "where_we_stand.md"],
    "columnist": ["rules.md", "where_we_stand.md"],
    "format_desk": ["rules.md", "where_we_stand.md"],
}

OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "wire_desk": schemas.WireDeskOutput,
    "assignment_editor": schemas.AssignmentEditorOutput,
    "beat_reporter": schemas.BeatReporterOutput,
    "fact_checker": schemas.FactCheckerOutput,
    "standards_editor": schemas.StandardsEditorOutput,
    "policy_desk": schemas.PolicyDeskOutput,
    "columnist": schemas.ColumnistOutput,
    "format_desk": schemas.FormatDeskOutput,
}

T = TypeVar("T", bound=BaseModel)


class PersonaError(RuntimeError):
    """A persona call finished without usable output (refusal, truncation, bad JSON)."""


def system_prompt(persona: str) -> str:
    parts = [(PERSONA_DIR / f"{persona}.md").read_text()]
    parts += [(CHARTER_DIR / name).read_text() for name in CHARTER_FILES[persona]]
    return "\n\n---\n\n".join(parts)


class Backend(Protocol):
    def call(self, persona: str, payload: dict) -> BaseModel: ...


class ClaudeBackend:
    """Runs a persona on Claude, with its prompt plus charter as the system prompt."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self._systems = {name: system_prompt(name) for name in CHARTER_FILES}

    def call(self, persona: str, payload: dict) -> BaseModel:
        output_model = OUTPUT_MODELS[persona]
        with self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            # The persona prompt never changes within a run, so cache it.
            system=[{
                "type": "text",
                "text": self._systems[persona],
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
            output_config={"effort": EFFORT},
            output_format=output_model,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            raise PersonaError(f"{persona} refused (category: {category})")
        if message.stop_reason == "max_tokens":
            raise PersonaError(f"{persona} hit max_tokens before finishing")
        if message.parsed_output is None:
            raise PersonaError(f"{persona} returned no parseable output")
        return message.parsed_output
