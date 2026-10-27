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
SourceType = Literal["pdf", "docx", "pptx", "html", "markdown", "text"]
SOURCE_TYPES: tuple[SourceType, ...] = ("pdf", "docx", "pptx", "html", "markdown", "text")
# Methods whose RAGFlow parser accepts PDF only ("file type not supported yet"): a tag
# defaulting to one of them must name a method for every other source type (findings E6).
PDF_ONLY_METHODS: frozenset[str] = frozenset({"paper", "manual"})
# Slug of our own platform tenant (alembic revision 0001), the owner of a tag that names
# no tenant (P1c-01).
INTERNAL_TENANT_SLUG = "internal"


class TagsConfigError(ValueError):
    """config/tags.toml is missing or invalid."""


class TagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_method: ChunkMethod
    chunk_method_by_type: dict[SourceType, ChunkMethod] = Field(default_factory=dict)
    # P1b-12: the slug of the one tenant whose workspaces may use this tag (a client's own
    # corpus). P1c-01: unset, the tag is the internal tenant's; sharing it with every
    # tenant is explicit (``shared = true``), and load_tags refuses a file that names
    # neither, so no tag is shared by omission.
    tenant: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    shared: bool = False

    @property
    def owner(self) -> str | None:
        """Slug of the one tenant that may use the tag; ``None`` for a shared tag."""
        return None if self.shared else (self.tenant or INTERNAL_TENANT_SLUG)

    def chunk_method_for(self, source_type: str) -> str:
        """The method a document of ``source_type`` should be parsed with in this tag."""
        return self.chunk_method_by_type.get(cast(SourceType, source_type), self.chunk_method)


class TagsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tags: dict[str, TagConfig] = Field(min_length=1)


def tags_for_tenant(tags: dict[str, TagConfig], tenant_slug: str) -> list[str]:
    """The tags a tenant's workspaces may use: its own and the shared ones, sorted."""
    return sorted(tag for tag, config in tags.items() if config.owner in (None, tenant_slug))


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
    unowned = sorted(
        tag for tag, config in parsed.tags.items() if not config.tenant and not config.shared
    )
    if unowned:
        # Before P1c-01 an unset tenant meant shared; a file written for that default
        # must say which it means (Phase 1b release 5.1, F4).
        raise TagsConfigError(
            f'{TAGS_FILE}: tags {unowned} name no tenant; set tenant = "<slug>" or shared = true'
        )
    both = sorted(tag for tag, config in parsed.tags.items() if config.tenant and config.shared)
    if both:
        raise TagsConfigError(f"{TAGS_FILE}: tags {both} set both tenant and shared = true")
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
