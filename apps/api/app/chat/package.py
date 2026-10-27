"""A workspace's package: which datasets it may retrieve from, and their provenance.

P1a-04: the package is per workspace (architecture §14.1). ``workspace_package``
reads the workspace's tags under the caller's tenant-scoped transaction (RLS hides
every other tenant's workspaces) and resolves them to RAGFlow dataset IDs through the
``datasets`` table. Dataset IDs never come from a request (CLAUDE.md): nothing here
takes or imports a request, and tests/test_workspaces.py checks that it stays so.
A workspace with no tags, or tags not yet synced, has no dataset and retrieves nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import Dataset
from app.tenancy.workspaces import Workspace

# Crawled or rendered web pages: untrusted text in prompts (CLAUDE.md).
UNTRUSTED_SOURCE_TYPES = frozenset({"html", "markdown", "text"})


class WorkspaceNotFound(LookupError):
    """No workspace with this ID in the current tenant."""


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


async def workspace_package(session: AsyncSession, workspace_id: UUID) -> Package:
    """The package of one workspace of the session's tenant, from the database only."""
    tags = await session.scalar(select(Workspace.tag_ids).where(Workspace.id == workspace_id))
    if tags is None:
        raise WorkspaceNotFound(str(workspace_id))
    return await resolve_package(session, tuple(sorted(set(tags))))


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
    """Map RAGFlow document IDs to their source register row, live sources only.

    Withdrawn and paused sources (P2A-02) have no provenance, so ``select_context`` drops
    their chunks even if RAGFlow returned one: a paused source never reaches a prompt. A
    new version of a paused source has none while it is parsed either (P2A-03): RAGFlow's
    parser makes new chunks available whatever the document's status, and the inherited
    pause is applied only once the parse is done.

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
            "AND s.status NOT IN ('withdrawn', 'paused') "
            # P2A-03: a new version of a paused source, while it parses, inherits the pause.
            "AND NOT (s.status = 'approved' AND EXISTS (SELECT 1 FROM sources p "
            "WHERE p.id = s.supersedes_id AND p.status = 'paused'))"
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
