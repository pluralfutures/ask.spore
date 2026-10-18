"""The tenant's package: which datasets it may retrieve from, and their provenance.

PHASE 0: one tenant, whose package is every tag in ``config/tags.toml``. Phase 1
replaces ``phase0_package_tags`` with the per-tenant package table; the rest is
unchanged. Dataset IDs come only from the ``datasets`` table, never from a request
(CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import Dataset

TAGS_FILE = "tags.toml"
# Crawled or rendered web pages: untrusted text in prompts (CLAUDE.md).
UNTRUSTED_SOURCE_TYPES = frozenset({"html", "markdown"})


class PackageError(RuntimeError):
    """config/tags.toml is missing or malformed."""


@dataclass(frozen=True)
class Package:
    tags: tuple[str, ...]
    dataset_ids: tuple[str, ...]  # sorted; resolved from the datasets table
    corpus_version: str  # changes whenever a source in these tags changes


@dataclass(frozen=True)
class Provenance:
    source_id: UUID
    type: str
    title: str
    publisher: str
    published_on: date | None
    canonical_url: str | None

    @property
    def untrusted(self) -> bool:
        return self.type in UNTRUSTED_SOURCE_TYPES


def phase0_package_tags(config_dir: Path) -> tuple[str, ...]:
    """PHASE 0 ONLY: the internal tenant's tags are all tags in config/tags.toml."""
    path = config_dir / TAGS_FILE
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackageError(f"tag file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PackageError(f"{path.name} is not valid TOML: {exc}") from exc
    tags = raw.get("tags")
    if not isinstance(tags, dict) or not tags:
        raise PackageError(f"{path.name} must define at least one [tags.<name>] table")
    return tuple(sorted(tags))


async def resolve_package(session: AsyncSession, tags: tuple[str, ...]) -> Package:
    """Dataset IDs and corpus version for ``tags``. Tags not yet synced have no dataset."""
    dataset_ids = tuple(
        sorted(
            (
                await session.scalars(
                    select(Dataset.ragflow_dataset_id).where(Dataset.tag.in_(tags))
                )
            ).all()
        )
    )
    # Any change to a source in the package (new, re-ingested, withdrawn) changes this.
    fingerprint = await session.scalar(
        text(
            "SELECT coalesce(string_agg(id::text || ':' || status || ':' "
            "|| ragflow_document_ids::text, ',' ORDER BY id), '') "
            "FROM sources WHERE tags && CAST(:tags AS text[])"
        ),
        {"tags": list(tags)},
    )
    digest = hashlib.sha256()
    for part in (",".join(tags), ",".join(dataset_ids), fingerprint or ""):
        digest.update(part.encode("utf-8") + b"\x00")
    return Package(tags=tags, dataset_ids=dataset_ids, corpus_version=digest.hexdigest()[:16])


async def provenance_by_document(
    session: AsyncSession, document_ids: list[str]
) -> dict[str, Provenance]:
    """Map RAGFlow document IDs to their source register row (withdrawn sources excluded).

    ``sources.ragflow_document_ids`` is matched on any string value it contains,
    whether it is stored as ``{dataset_or_tag: document_id}`` or as a list.
    """
    if not document_ids:
        return {}
    rows = await session.execute(
        text(
            "SELECT d.doc #>> '{}' AS document_id, s.id, s.type, s.title, s.publisher, "
            "s.published_on, s.canonical_url "
            "FROM sources s "
            "CROSS JOIN LATERAL jsonb_path_query(s.ragflow_document_ids, 'strict $.**') AS d(doc) "
            "WHERE jsonb_typeof(d.doc) = 'string' "
            "AND d.doc #>> '{}' = ANY(CAST(:ids AS text[])) "
            "AND s.status <> 'withdrawn'"
        ),
        {"ids": document_ids},
    )
    return {
        row.document_id: Provenance(
            source_id=row.id,
            type=row.type,
            title=row.title,
            publisher=row.publisher,
            published_on=row.published_on,
            canonical_url=row.canonical_url,
        )
        for row in rows
    }
