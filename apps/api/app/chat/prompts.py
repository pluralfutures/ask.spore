"""Versioned prompt templates (P0-12).

Prompts are files under ``<config dir>/prompts/<name>/<version>.md``; the active
version of each is set in ``config/models.toml`` ``[prompts]``. Prompt text lives
only in those files: code loads them, it never builds instructions from strings.
Startup (app.core.config) refuses to start if an active version file is missing.

P1a-06: a mode prompt may hold one workspace-instructions slot (``config/README.md``):
a section between ``{{#workspace_instructions}}`` and ``{{/workspace_instructions}}``
around one ``{{workspace_instructions}}`` placeholder. ``render_system`` fills it with
the workspace's tenant-authored text, capped and escaped, or drops the section when
there is none. The tenant text is the only thing the code inserts, and only there.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.core.config import Settings

PromptName = Literal["corpus_only", "general_knowledge", "rewrite", "judge"]
AnswerPrompt = Literal["corpus_only", "general_knowledge"]

INSTRUCTIONS_MAX_CHARS = 2000  # app.tenancy.workspaces.PROMPT_MAX_CHARS
SLOT_OPEN = "{{#workspace_instructions}}"
SLOT_CLOSE = "{{/workspace_instructions}}"
PLACEHOLDER = "{{workspace_instructions}}"
_SECTION = re.compile(re.escape(SLOT_OPEN) + r"(.*?)" + re.escape(SLOT_CLOSE), re.S)
# C0 controls other than tab and newline, and DEL: no business in instructions.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_BLANK_LINES = re.compile(r"\n{3,}")


class PromptError(RuntimeError):
    """A prompt file is missing or empty."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def ref(self) -> str:
        """Stable identifier recorded with answers and cache keys, e.g. ``corpus_only/v1``."""
        return f"{self.name}/{self.version}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def prompt_path(config_dir: Path, name: str, version: str) -> Path:
    return config_dir / "prompts" / name / f"{version}.md"


@lru_cache(maxsize=32)
def load_prompt(config_dir: Path, name: str, version: str) -> Prompt:
    path = prompt_path(config_dir, name, version)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptError(f"prompt file not found: {path}") from exc
    if not text:
        raise PromptError(f"prompt file is empty: {path}")
    return Prompt(name=name, version=version, text=text)


def active_prompt(settings: Settings, name: PromptName) -> Prompt:
    """The prompt version selected in ``models.toml`` ``[prompts]``."""
    version: str = getattr(settings.models.prompts, name)
    return load_prompt(settings.config_dir, name, version)


def check_slot(text: str) -> list[str]:
    """Problems with a template's workspace-instructions slot; none when it has no slot."""
    opens, closes, placeholders = (text.count(t) for t in (SLOT_OPEN, SLOT_CLOSE, PLACEHOLDER))
    if opens == closes == placeholders == 0:
        return []
    section = _SECTION.search(text)
    if (opens, closes, placeholders) != (1, 1, 1) or section is None:
        return [
            "needs exactly one {{#workspace_instructions}} ... {{/workspace_instructions}} "
            "section holding one {{workspace_instructions}} placeholder"
        ]
    if PLACEHOLDER not in section.group(1):
        return ["the {{workspace_instructions}} placeholder must be inside its section"]
    return []


def escape_instructions(text: str) -> str:
    """Tenant text as it may appear in the slot: capped, control characters dropped and
    ``&``, ``<`` and ``>`` escaped, so it cannot close or forge an element."""
    cleaned = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    return html.escape(cleaned[:INSTRUCTIONS_MAX_CHARS].strip(), quote=False)


def render_system(prompt: Prompt, instructions: str) -> str:
    """The system prompt with the workspace's additional instructions in their slot.

    A template without a slot (``corpus_only/v1``) is returned unchanged; empty
    instructions remove the whole section, so nothing tenant-shaped remains.
    """
    section = _SECTION.search(prompt.text)
    if section is None:
        return prompt.text
    escaped = escape_instructions(instructions)
    if escaped:
        # str.replace inserts the tenant text literally; nothing re-scans what it inserted.
        body = section.group(1).replace(PLACEHOLDER, escaped)
        text = prompt.text[: section.start()] + body + prompt.text[section.end() :]
    else:
        text = prompt.text[: section.start()] + prompt.text[section.end() :]
    return _BLANK_LINES.sub("\n\n", text).strip()
