"""Withdrawal and supersession (P1b-03): the ``withdraw_source`` job.

One job per source (architecture §6.3), run by the worker, idempotent on retry:

1. delete the source's document from every RAGFlow dataset it is in (the register's
   ``ragflow_document_ids``), recording what is left after each deletion; a document
   RAGFlow no longer has counts as deleted;
2. flag the stored citations of the source in every tenant's history, as
   ``askspore_content`` (identifier and flag columns only): ``superseded_at`` when a
   re-ingested version of the file replaced it, ``withdrawn_at`` otherwise. Every
   withdrawal blanks the stored excerpts as well, for this source and the earlier
   versions it replaced, whatever the grounds (owner decision 3, Oct 23, 2026; until
   then only a takedown on licence grounds did), and labels those versions' citations
   withdrawn too; the citation, its provenance and its label stay. A supersession
   keeps them: the document is still in the corpus;
3. mark the register row ``withdrawn`` with its date and reason, audited (a paused
   source is withdrawn the same way, its pause cleared: P2A-01);
4. delete our stored copy of the file, unless another live source has the same content,
   and a crawled page's raw HTML snapshot (P1b-04) likewise;
5. purge every tenant's answer-cache entries that cite the source (cache values record
   their source IDs from P1b-03 on; older values are matched by their citations).

A withdrawal is requested by a reviewer (``app.content.register.request_withdrawal``);
a supersession is enqueued by the ingestion of the replacing source.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Container
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.chat.models import Citation
from app.content.models import Source
from app.content.store import StoredFileError, relative_path, remove
from app.core import cache
from app.core.db import CONTENT_ROLE, role_session, tenant_session
from app.retrieval.ragflow import RagflowClient, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID

ANSWER_PREFIX = "answer:"
SUPERSEDED_REASON = "superseded by a re-ingested version"

Kind = Literal["withdrawn", "superseded"]


@dataclass(frozen=True)
class WithdrawResult:
    source_id: UUID
    status: Literal["withdrawn", "failed", "refused"]
    kind: Kind = "withdrawn"
    error_code: str | None = None
    citations_flagged: int = 0
    cache_entries_purged: int = 0


def _cites(raw: str, source_ids: Container[str]) -> bool:
    try:
        value = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(value, dict):
        return False
    cited = value.get("source_ids")
    if not isinstance(cited, list):  # cached before P1b-03: read the citations
        cited = [c.get("source_id") for c in value.get("citations") or [] if isinstance(c, dict)]
    return any(isinstance(s, str) and s in source_ids for s in cited)


async def purge_answer_cache(
    factory: async_sessionmaker[AsyncSession], source_ids: Container[str]
) -> int:
    """Delete every tenant's cached answers that cite one of ``source_ids``."""
    async with role_session(factory, CONTENT_ROLE) as session:
        tenant_ids = list((await session.scalars(text("SELECT id FROM tenants"))).all())
    purged = 0
    for tenant_id in tenant_ids:
        stale = [
            key
            async for key, raw in cache.scan(tenant_id, ANSWER_PREFIX)
            if _cites(raw, source_ids)
        ]
        for key in stale:
            await cache.delete(tenant_id, key)
        purged += len(stale)
    return purged


async def flag_citations(
    factory: async_sessionmaker[AsyncSession], source_id: UUID, kind: Kind
) -> int:
    """Set ``superseded_at`` or ``withdrawn_at`` on the source's citations in every tenant."""
    column = Citation.superseded_at if kind == "superseded" else Citation.withdrawn_at
    async with role_session(factory, CONTENT_ROLE) as session:
        result = await session.execute(
            update(Citation)
            .where(Citation.source_id == source_id, column.is_(None))
            .values({column: func.now()})
            .execution_options(synchronize_session=False)
        )
    return int(getattr(result, "rowcount", 0) or 0)


async def blank_excerpts(
    factory: async_sessionmaker[AsyncSession], source_ids: Collection[UUID]
) -> int:
    """Blank the stored excerpts of the sources' citations in every tenant; the citation,
    its provenance and its flags stay. ``askspore_content`` may write only ''."""
    if not source_ids:
        return 0
    async with role_session(factory, CONTENT_ROLE) as session:
        result = await session.execute(
            update(Citation)
            .where(Citation.source_id.in_(list(source_ids)))
            .values(excerpt="")
            .execution_options(synchronize_session=False)
        )
    return int(getattr(result, "rowcount", 0) or 0)


async def _versions(session: AsyncSession, source_id: UUID) -> list[UUID]:
    """The source and every earlier version it replaced, newest first."""
    chain = [source_id]
    current: UUID | None = await session.scalar(
        select(Source.supersedes_id).where(Source.id == source_id)
    )
    while current is not None and current not in chain:
        chain.append(current)
        current = await session.scalar(select(Source.supersedes_id).where(Source.id == current))
    return chain


async def _gone(client: RagflowClient, dataset_id: str, document_id: str) -> bool:
    """True when RAGFlow no longer has the document (deleted earlier, or by hand)."""
    try:
        await client.get_document(dataset_id, document_id)
    except RagflowError as exc:
        return exc.code in ("not_found", 404)
    return False


async def _kind(session: AsyncSession, source_id: UUID) -> Kind:
    replacement = await session.scalar(
        select(Source.id).where(
            Source.supersedes_id == source_id,
            # P2A-03: a new version ingested paused replaces the old one all the same.
            Source.status.in_(("ingested", "paused")),
        )
    )
    return "superseded" if replacement is not None else "withdrawn"


async def withdraw_source(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    source_id: UUID,
    *,
    content_root: Path,
) -> WithdrawResult:
    """Run the cascade for one source; ``failed`` (with a code) leaves it to a retry."""
    async with factory() as session:
        row = await session.scalar(select(Source).where(Source.id == source_id))
        if row is None:
            return WithdrawResult(source_id, "refused", error_code="no_source")
        kind = await _kind(session, source_id)
        # Owner decision 3 (Oct 23, 2026): every withdrawal blanks, a supersession does not.
        blank = kind == "withdrawn"
        versions = await _versions(session, source_id) if blank else []
    if row.status not in ("ingested", "failed", "paused", "withdrawn"):
        return WithdrawResult(source_id, "refused", kind, error_code="not_withdrawable")

    # 1. RAGFlow: every dataset the register maps the source into.
    remaining: dict[str, str] = dict(row.ragflow_document_ids or {})
    try:
        for dataset_id, document_id in list(remaining.items()):
            try:
                await client.delete_documents(dataset_id, [document_id])
            except RagflowError as exc:
                # Not found means already deleted: done, not a failure to retry.
                if exc.code != 404 and not await _gone(client, dataset_id, document_id):
                    raise
            del remaining[dataset_id]
    except RagflowError as exc:
        async with factory() as session, session.begin():
            await session.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(ragflow_document_ids=remaining, updated_at=func.now())
            )
        return WithdrawResult(source_id, "failed", kind, error_code=exc.error_code)

    # 2. Stored history, every tenant; excerpts blanked unless superseded. The earlier
    # versions are the same document: labelled withdrawn too (P1c-14).
    flagged = await flag_citations(factory, source_id, kind)
    if blank:
        for version in versions[1:]:
            await flag_citations(factory, version, "withdrawn")
        await blank_excerpts(factory, versions)

    # 3. The register row, audited.
    if row.status != "withdrawn":
        async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
            await session.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(
                    status="withdrawn",
                    withdrawn_at=func.now(),
                    withdrawal_reason=func.coalesce(
                        Source.withdrawal_reason,
                        SUPERSEDED_REASON if kind == "superseded" else "withdrawn",
                    ),
                    ragflow_document_ids={},
                    chunk_count=None,
                    error=None,
                    stored_path=None,
                    # A paused source withdrawn (P2A-01): the pause ends with it.
                    paused_at=None,
                    paused_by=None,
                    pause_reason=None,
                    updated_at=func.now(),
                )
            )
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=None,
                event="source.withdrawn",
                metadata={
                    "source_id": str(source_id),
                    "before": {"status": row.status},
                    "after": {"status": "withdrawn"},
                    "outcome": kind,
                    "count": flagged,
                    "excerpts_blanked": blank,
                },
            )

    # 4. Our copy of the file, unless another live source holds the same content.
    if row.file_sha256 is not None:
        async with factory() as session:
            shared = await session.scalar(
                select(func.count())
                .select_from(Source)
                .where(
                    Source.file_sha256 == row.file_sha256,
                    Source.id != source_id,
                    Source.status != "withdrawn",
                )
            )
        if not shared:
            try:
                remove(content_root, relative_path(row.file_sha256, row.type))
            except (StoredFileError, ValueError):
                pass  # nothing usable to remove
    # A crawled page's raw HTML snapshot (P1b-04) goes with it, unless shared.
    if row.snapshot_path is not None:
        async with factory() as session:
            shared = await session.scalar(
                select(func.count())
                .select_from(Source)
                .where(
                    Source.snapshot_path == row.snapshot_path,
                    Source.id != source_id,
                    Source.status != "withdrawn",
                )
            )
        if not shared:
            try:
                remove(content_root, row.snapshot_path)
            except StoredFileError:
                pass

    # 5. Cached answers, every tenant.
    try:
        purged = await purge_answer_cache(factory, {str(source_id)})
    except Exception:  # the row is withdrawn; a retry of the job purges again
        return WithdrawResult(source_id, "failed", kind, "cache_unavailable", flagged)
    return WithdrawResult(source_id, "withdrawn", kind, None, flagged, purged)
