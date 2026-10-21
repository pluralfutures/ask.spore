"""Source register transitions (P1b-01): propose, approve, reject, retry.

``proposed -> approved -> ingested -> withdrawn``, plus ``failed`` (retryable: a
reviewer sends it back to ``approved``) and ``rejected``. No document reaches RAGFlow
without an approved row (architecture §6.1): ``propose`` only records the row and
stages the file under ``[files] content_root``; ingestion (``app.content.ingest``)
refuses a source that is not ``approved``.

Every transition takes the acting internal user, checks their content role inside
the same transaction, and writes an audit event under the internal tenant with the
status before and after. An approval also names the reviewer's roles and whether
they approve their own proposal (allowed and audited by owner decision, Oct 21, 2026).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditValue, record
from app.content.ingest import IngestError, SourceFile, SourceMetadata
from app.content.models import Dataset, Source
from app.content.roles import EDITOR, REVIEWER, require
from app.content.store import STORABLE_TYPES, stage
from app.content.tags import TagConfig
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID

MAX_NOTE_LENGTH = 2000

SubmissionOutcome = Literal["proposed", "pending", "duplicate", "retag", "taken_down"]


@dataclass(frozen=True)
class Submission:
    """What ``propose`` did with a file.

    - ``proposed``: a new register row, status ``proposed``;
    - ``pending``: a row with the same content already waits (``proposed``,
      ``approved`` or ``failed``; ``status`` says which), nothing new recorded;
    - ``duplicate``: the same content is already ingested in every requested tag;
    - ``retag``: it is ingested, and the request adds ``new_tags`` (needs a reviewer);
    - ``taken_down``: the same content was withdrawn after a takedown request; nothing is
      proposed (a withdrawn file must not come back through a re-run of the manifest).
    """

    source_id: UUID
    outcome: SubmissionOutcome
    status: str
    new_tags: tuple[str, ...] = ()


class RegisterError(ValueError):
    """A transition is not allowed from the row's current state. ``code`` is safe to log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate(
    tags_config: Mapping[str, TagConfig], source: SourceFile, metadata: SourceMetadata
) -> tuple[str, ...]:
    tags = tuple(dict.fromkeys(metadata.tags))
    if not tags:
        raise IngestError("no_tag", "at least one --tag is required")
    unknown = [tag for tag in tags if tag not in tags_config]
    if unknown:
        raise IngestError("unknown_tag", f"tags not in config/tags.toml: {', '.join(unknown)}")
    for name, value in (
        ("title", metadata.title),
        ("publisher", metadata.publisher),
        ("licence", metadata.licence_basis),
    ):
        if not value.strip():
            raise IngestError("missing_metadata", f"--{name} must not be empty")
    if metadata.downloadable and source.type not in STORABLE_TYPES:
        raise IngestError("not_downloadable", "only PDF, DOCX and PPTX files can be downloadable")
    return tags


async def _audit(
    session: AsyncSession,
    actor: UUID | None,
    event: str,
    source_id: UUID,
    before: str | None,
    after: str,
    **extra: AuditValue,
) -> None:
    await record(
        session,
        tenant_id=INTERNAL_TENANT_ID,
        actor_user_id=actor,
        event=event,
        metadata={
            "source_id": str(source_id),
            "before": {} if before is None else {"status": before},
            "after": {"status": after},
            **extra,
        },
    )


async def propose(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    metadata: SourceMetadata,
    *,
    content_root: Path,
    proposer_id: UUID | None,
) -> Submission:
    """Record ``source`` as a proposal; raises IngestError, recording nothing, on bad input.

    The file is staged under ``content_root`` by hash, so ingestion can run elsewhere.
    ``proposer_id`` must hold ``content_editor``; None means the operator's shell (the
    manifest CLI run without a proposer), recorded as such in the audit event.
    """
    tags = _validate(tags_config, source, metadata)
    try:
        staged = stage(content_root, source.sha256, source.type, source.content)
    except OSError as exc:
        raise IngestError("store_failed", f"cannot store the file: {exc.strerror}") from None
    stored_path = staged if source.type in STORABLE_TYPES else None

    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        if proposer_id is not None:
            await require(session, proposer_id, EDITOR)
        datasets = set(
            (await session.scalars(select(Dataset.tag).where(Dataset.tag.in_(tags)))).all()
        )
        missing = [tag for tag in tags if tag not in datasets]
        if missing:
            raise IngestError(
                "no_dataset",
                f"no dataset for {', '.join(missing)}; run `ask-spore datasets sync` first",
            )
        same = (
            await session.execute(
                select(
                    Source.id,
                    Source.status,
                    Source.tags,
                    Source.stored_path,
                    Source.takedown_reference,
                )
                .where(Source.file_sha256 == source.sha256)
                .order_by(Source.created_at)
            )
        ).all()
        taken_down = next(
            (r for r in same if r.status == "withdrawn" and r.takedown_reference), None
        )
        if taken_down is not None:
            return Submission(taken_down.id, "taken_down", "withdrawn")
        ingested = next((r for r in same if r.status == "ingested"), None)
        if ingested is not None:
            if ingested.stored_path is None and stored_path is not None:
                await session.execute(
                    update(Source).where(Source.id == ingested.id).values(stored_path=stored_path)
                )
            new_tags = tuple(tag for tag in tags if tag not in ingested.tags)
            if new_tags:
                return Submission(ingested.id, "retag", "ingested", new_tags)
            return Submission(ingested.id, "duplicate", "ingested")
        waiting = next((r for r in same if r.status in ("proposed", "approved", "failed")), None)
        if waiting is not None:
            return Submission(waiting.id, "pending", waiting.status)

        row = Source(
            type=source.type,
            title=metadata.title.strip(),
            publisher=metadata.publisher.strip(),
            published_on=metadata.published_on,
            canonical_url=metadata.canonical_url,
            licence_basis=metadata.licence_basis.strip(),
            tags=list(tags),
            status="proposed",
            file_sha256=source.sha256,
            stored_path=stored_path,
            downloadable=metadata.downloadable,
            proposed_by=proposer_id,
        )
        session.add(row)
        await session.flush()
        await _audit(
            session,
            proposer_id,
            "source.proposed",
            row.id,
            None,
            "proposed",
            method="cli" if proposer_id is None else "editor",
        )
        return Submission(row.id, "proposed", "proposed")


async def _locked(session: AsyncSession, source_id: UUID) -> Source:
    row = await session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if row is None:
        raise RegisterError("no_source")
    return row


def _note(note: str | None, *, required: bool) -> str | None:
    note = (note or "").strip() or None
    if required and note is None:
        raise RegisterError("note_required")
    if note is not None and len(note) > MAX_NOTE_LENGTH:
        raise RegisterError("note_too_long")
    return note


async def _review(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    allowed_from: Sequence[str],
    to: str,
    event: str,
    note: str | None,
) -> None:
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        before = row.status
        if before not in allowed_from:
            raise RegisterError(f"not_{'_or_'.join(allowed_from)}")
        values: dict[str, object] = {"status": to, "updated_at": func.now()}
        if to == "approved":
            values |= {"approved_by": reviewer_id, "approved_at": func.now(), "error": None}
        if note is not None:
            values["review_note"] = note
        await session.execute(update(Source).where(Source.id == source_id).values(**values))
        self_approval = row.proposed_by == reviewer_id
        await _audit(
            session,
            reviewer_id,
            event,
            source_id,
            before,
            to,
            roles=sorted(roles),
            self_approval=self_approval,
        )


async def approve(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    note: str | None = None,
) -> None:
    """``proposed -> approved``. The reviewer may be the proposer (audited as such)."""
    await _review(
        factory,
        source_id,
        reviewer_id,
        allowed_from=("proposed",),
        to="approved",
        event="source.approved",
        note=_note(note, required=False),
    )


async def reject(
    factory: async_sessionmaker[AsyncSession], source_id: UUID, reviewer_id: UUID, *, note: str
) -> None:
    """``proposed -> rejected``, with the reviewer's note."""
    await _review(
        factory,
        source_id,
        reviewer_id,
        allowed_from=("proposed",),
        to="rejected",
        event="source.rejected",
        note=_note(note, required=True),
    )


async def retry(
    factory: async_sessionmaker[AsyncSession], source_id: UUID, reviewer_id: UUID
) -> None:
    """``failed -> approved``: the reviewer sends a failed source back for ingestion."""
    await _review(
        factory,
        source_id,
        reviewer_id,
        allowed_from=("failed",),
        to="approved",
        event="source.retried",
        note=None,
    )


async def approve_retag(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    new_tags: Sequence[str],
) -> None:
    """A reviewer approves linking an ingested source into more tags' datasets."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        if row.status != "ingested":
            raise RegisterError("not_ingested")
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=reviewer_id,
            event="source.retag_approved",
            metadata={
                "source_id": str(source_id),
                "before": {"tag_ids": list(row.tags)},
                "after": {"tag_ids": list(dict.fromkeys([*row.tags, *new_tags]))},
                "roles": sorted(roles),
            },
        )
