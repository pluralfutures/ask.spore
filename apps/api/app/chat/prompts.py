"""Versioned prompt templates (P0-12).

Prompts are files under ``<config dir>/prompts/<name>/<version>.md``; the active
version of each is set in ``config/models.toml`` ``[prompts]``. Prompt text lives
only in those files: code loads them, it never builds instructions from strings.
Startup (app.core.config) refuses to start if an active version file is missing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.core.config import Settings

PromptName = Literal["corpus_only", "rewrite"]


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
