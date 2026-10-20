"""Content tags and their chunking methods: config/tags.toml (P0-08)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

TAGS_FILE = "tags.toml"
DATASET_NAME_PREFIX = "ask-spore-"
TAG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

# RAGFlow v0.27.2 chunking methods that apply to our source types.
ChunkMethod = Literal["naive", "paper", "book", "presentation", "manual", "laws", "one"]
# Must equal app.content.models.SOURCE_TYPES (tests/test_tags.py).
SourceType = Literal["pdf", "docx", "pptx", "html", "markdown"]
SOURCE_TYPES: tuple[SourceType, ...] = ("pdf", "docx", "pptx", "html", "markdown")
# Methods whose RAGFlow parser accepts PDF only ("file type not supported yet"): a tag
# defaulting to one of them must name a method for every other source type (findings E6).
PDF_ONLY_METHODS: frozenset[str] = frozenset({"paper", "manual"})


class TagsConfigError(ValueError):
    """config/tags.toml is missing or invalid."""


class TagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_method: ChunkMethod
    chunk_method_by_type: dict[SourceType, ChunkMethod] = Field(default_factory=dict)

    def chunk_method_for(self, source_type: str) -> str:
        """The method a document of ``source_type`` should be parsed with in this tag."""
        return self.chunk_method_by_type.get(cast(SourceType, source_type), self.chunk_method)


class TagsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tags: dict[str, TagConfig] = Field(min_length=1)


def dataset_name(tag: str) -> str:
    """Name of the RAGFlow dataset for ``tag``."""
    return DATASET_NAME_PREFIX + tag


def load_tags(config_dir: Path) -> dict[str, TagConfig]:
    path = config_dir / TAGS_FILE
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TagsConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise TagsConfigError(f"{TAGS_FILE} is not valid TOML: {exc}") from None
    try:
        parsed = TagsFile.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise TagsConfigError(f"{TAGS_FILE}: {problems}") from None
    bad = [tag for tag in parsed.tags if not re.fullmatch(TAG_PATTERN, tag)]
    if bad:
        raise TagsConfigError(f"{TAGS_FILE}: tag names must be lowercase-hyphenated: {bad}")
    for tag, config in parsed.tags.items():
        uncovered = [
            source_type
            for source_type in SOURCE_TYPES
            if source_type != "pdf" and config.chunk_method_for(source_type) in PDF_ONLY_METHODS
        ]
        if uncovered:
            raise TagsConfigError(
                f"{TAGS_FILE}: tag {tag!r} would parse {uncovered} with a PDF-only method; "
                "set chunk_method_by_type for them"
            )
    return dict(parsed.tags)
