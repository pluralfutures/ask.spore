"""Source register transitions (P1b-01): propose, approve, reject, retry, pause, resume.

``proposed -> approved -> ingested -> withdrawn``, plus ``failed`` (retryable: a
reviewer sends it back to ``approved``), ``rejected``, and ``ingested <-> paused``
(P2A-01: a reviewer takes a source out of retrieval without destroying it; a paused
source can still be withdrawn, and a pause never satisfies a takedown). No document reaches RAGFlow
without an approved row (architecture §6.1): ``propose`` only records the row and
stages the file under ``[files] content_root``; ingestion (``app.content.ingest``)
refuses a source that is not ``approved``.

Approval (and a retry) enqueues one ``ingest_source`` job in the same transaction
(P1b-02), so a committed approval always has its job; the worker does the rest.

Every transition takes the acting internal user, checks their content role inside
the same transaction, and writes an audit event under the internal tenant with the
status before and after. An approval also names the reviewer's roles and whether
they approve their own proposal (allowed and audited by owner decision, Oct 21, 2026).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditValue, record
from app.content.ingest import IngestError, SourceFile, SourceMetadata
from app.content.jobs import enqueue
from app.content.models import Dataset, SitePage, Source
from app.content.roles import EDITOR, REVIEWER, RoleError, require, roles_of
from app.content.store import STORABLE_TYPES, stage
from app.content.tags import TagConfig
from app.content.withdraw import purge_answer_cache
from app.core.db import tenant_session
from app.core.logging import log
from app.retrieval.ragflow import RagflowClient, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID

MAX_NOTE_LENGTH = 2000
MAX_REFERENCE_LENGTH = 128
TAKEDOWN_WORKING_DAYS = 10  # architecture §6.3: from a valid request

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
    # proposed: ingested sources at the same canonical link, which the reviewer may
    # choose to replace (owner decision 4, Oct 22, 2026); nothing is replaced unasked.
    possible_replacements: tuple[UUID, ...] = ()
    # proposed: the one ingested source with the same canonical link and the same title,
    # which the new file replaces once ingested (owner decision 3, Oct 23, 2026).
    replaces: UUID | None = None


@dataclass(frozen=True)
class Choice:
    """The reviewer's answer to "possible replacement of <source>": replace that source,
    or keep both (owner decision 4, Oct 22, 2026)."""

    replaces: UUID | None = None
    keep_both: bool = False


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


async def replacement_candidates(
    session: AsyncSession, canonical_url: str | None, *, exclude: UUID | None = None
) -> list[UUID]:
    """Ingested sources at ``canonical_url`` that a new file there may replace.

    Owner decision 4 (Oct 22, 2026): a new file at an existing canonical link does not
    replace the old document automatically; the reviewer chooses "replace" or "keep
    both" when approving. Crawled pages are matched by their site instead (P1b-04).
    """
    if not canonical_url:
        return []
    query = (
        select(Source.id)
        .where(
            Source.canonical_url == canonical_url,
            Source.status == "ingested",
            Source.site_id.is_(None),
        )
        .order_by(Source.created_at)
    )
    if exclude is not None:
        query = query.where(Source.id != exclude)
    return list((await session.scalars(query)).all())


def same_title(a: str, b: str) -> bool:
    """Titles match ignoring case and runs of whitespace (owner decision 3)."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


async def _being_replaced(session: AsyncSession, source_id: UUID, *, by: UUID | None) -> bool:
    """Another approved (or ingested, or failed) proposal already replaces the source."""
    query = select(Source.id).where(
        Source.supersedes_id == source_id,
        Source.status.in_(("approved", "ingested", "failed")),
    )
    if by is not None:
        query = query.where(Source.id != by)
    return await session.scalar(query.limit(1)) is not None


async def exact_replacement(
    session: AsyncSession, canonical_url: str | None, title: str, *, exclude: UUID | None = None
) -> UUID | None:
    """The ingested source a new file at ``canonical_url`` replaces without asking.

    Owner decision 3 (Oct 23, 2026): a re-ingestion replaces a document only when both
    the canonical link and the title match; a link match with another title stays a
    possible replacement for the reviewer (decision 4 of Oct 22). Exactly one ingested
    source at the link may have the title, and no other proposal may already be
    replacing it; otherwise there is no automatic replacement.
    """
    candidates = await replacement_candidates(session, canonical_url, exclude=exclude)
    if not candidates:
        return None
    titles = (
        await session.execute(select(Source.id, Source.title).where(Source.id.in_(candidates)))
    ).all()
    matches = [r.id for r in titles if same_title(r.title, title)]
    if len(matches) != 1 or await _being_replaced(session, matches[0], by=exclude):
        return None
    match: UUID = matches[0]
    return match


async def propose(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    metadata: SourceMetadata,
    *,
    content_root: Path,
    proposer_id: UUID | None,
    licence_file_path: str | None = None,
) -> Submission:
    """Record ``source`` as a proposal; raises IngestError, recording nothing, on bad input.

    ``proposer_id`` must hold ``content_editor`` (checked before anything is written);
    None means the operator's shell (the manifest CLI run without a proposer), recorded
    as such in the audit event. The file is staged under ``content_root`` by hash, so
    ingestion can run elsewhere, only once the proposal is to be recorded.
    """
    tags = _validate(tags_config, source, metadata)

    def staged() -> str:
        try:
            return stage(content_root, source.sha256, source.type, source.content)
        except OSError as exc:
            raise IngestError("store_failed", f"cannot store the file: {exc.strerror}") from None

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
            # A re-tag reads the staged copy; sources ingested before P1b-02 have none.
            path = staged()
            if ingested.stored_path is None and source.type in STORABLE_TYPES:
                await session.execute(
                    update(Source).where(Source.id == ingested.id).values(stored_path=path)
                )
            new_tags = tuple(tag for tag in tags if tag not in ingested.tags)
            if new_tags:
                return Submission(ingested.id, "retag", "ingested", new_tags)
            return Submission(ingested.id, "duplicate", "ingested")
        waiting = next((r for r in same if r.status in ("proposed", "approved", "failed")), None)
        if waiting is not None:
            return Submission(waiting.id, "pending", waiting.status)
        title = metadata.title.strip()
        replaces = await exact_replacement(session, metadata.canonical_url, title)
        candidates = (
            [] if replaces else await replacement_candidates(session, metadata.canonical_url)
        )

        path = staged()
        row = Source(
            type=source.type,
            title=title,
            publisher=metadata.publisher.strip(),
            published_on=metadata.published_on,
            canonical_url=metadata.canonical_url,
            licence_basis=metadata.licence_basis.strip(),
            tags=list(tags),
            status="proposed",
            file_sha256=source.sha256,
            stored_path=path if source.type in STORABLE_TYPES else None,
            downloadable=metadata.downloadable,
            proposed_by=proposer_id,
            licence_file_path=licence_file_path,
            supersedes_id=replaces,
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
        return Submission(
            row.id,
            "proposed",
            "proposed",
            possible_replacements=tuple(candidates),
            replaces=replaces,
        )


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
    parse_timeout: float | None = None,
    choice: Choice | None = None,
) -> UUID | None:
    """The transition; the ``ingest_source`` job's ID when the row becomes approved.

    With ``choice`` (a first approval), a proposal at the canonical link of ingested
    sources needs the reviewer's decision, replace one of them or keep both, unless it
    has the same title as exactly one of them (recorded at proposal as ``supersedes_id``):
    that one is replaced without a choice, and "keep both" or another source overrides.
    """
    job_id: UUID | None = None
    extra: dict[str, AuditValue] = {}
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        before = row.status
        if before not in allowed_from:
            raise RegisterError(f"not_{'_or_'.join(allowed_from)}")
        values: dict[str, object] = {"status": to, "updated_at": func.now()}
        if to == "approved":
            values |= {"approved_by": reviewer_id, "approved_at": func.now(), "error": None}
        if choice is not None:
            candidates = await replacement_candidates(session, row.canonical_url, exclude=source_id)
            if choice.replaces is not None and choice.keep_both:
                raise RegisterError("replace_or_keep_both")
            # Same link and same title, recorded at proposal (owner decision 3): still
            # the one exact match now, or the reviewer decides as for any other.
            automatic = row.supersedes_id
            if automatic is not None and automatic != await exact_replacement(
                session, row.canonical_url, row.title, exclude=source_id
            ):
                automatic = None
            values["supersedes_id"] = None
            if choice.replaces is not None:
                if choice.replaces not in candidates:
                    raise RegisterError("not_a_replacement_candidate")
                if await _being_replaced(session, choice.replaces, by=source_id):
                    raise RegisterError("already_being_replaced")
                values["supersedes_id"] = choice.replaces
                extra["replaces"] = str(choice.replaces)
            elif choice.keep_both and candidates:
                extra["keep_both"] = True
            elif automatic is not None:
                values["supersedes_id"] = automatic
                extra |= {"replaces": str(automatic), "method": "same_link_and_title"}
            elif candidates:
                raise RegisterError("replacement_choice_required")
        if note is not None:
            values["review_note"] = note
        await session.execute(update(Source).where(Source.id == source_id).values(**values))
        if to == "approved":
            payload: dict[str, str | float] = {"source_id": str(source_id)}
            if parse_timeout is not None:
                payload["parse_timeout"] = parse_timeout
            job_id = await enqueue(session, "ingest_source", payload, created_by=reviewer_id)
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
            **extra,
        )
    return job_id


async def approve(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    note: str | None = None,
    parse_timeout: float | None = None,
    replaces: UUID | None = None,
    keep_both: bool = False,
) -> UUID:
    """``proposed -> approved``; returns the ``ingest_source`` job it enqueued. The
    reviewer may be the proposer (audited as such).

    When ingested sources share the proposal's canonical link, the reviewer must choose
    (owner decision 4, Oct 22, 2026): ``replaces`` names the one the new file replaces
    (once ingested, the old one is withdrawn and its citations show as superseded), or
    ``keep_both`` keeps them side by side. Without a choice the approval is refused
    (``replacement_choice_required``), unless the proposal also has the title of exactly
    one of them: that one is replaced (owner decision 3, Oct 23, 2026), audited with
    ``method: same_link_and_title``.
    """
    job_id = await _review(
        factory,
        source_id,
        reviewer_id,
        allowed_from=("proposed",),
        to="approved",
        event="source.approved",
        note=_note(note, required=False),
        parse_timeout=parse_timeout,
        choice=Choice(replaces, keep_both),
    )
    if job_id is None:
        raise AssertionError("an approval always enqueues a job")
    return job_id


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
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    parse_timeout: float | None = None,
) -> UUID:
    """``failed -> approved``: the reviewer sends a failed source back for ingestion;
    returns the ``ingest_source`` job it enqueued."""
    job_id = await _review(
        factory,
        source_id,
        reviewer_id,
        allowed_from=("failed",),
        to="approved",
        event="source.retried",
        note=None,
        parse_timeout=parse_timeout,
    )
    if job_id is None:
        raise AssertionError("an approval always enqueues a job")
    return job_id


async def approve_retag(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    new_tags: Sequence[str],
    *,
    downloadable: bool,
    parse_timeout: float | None = None,
) -> UUID:
    """A reviewer approves linking an ingested source into more tags' datasets, with the
    request's download flag; returns the ``ingest_source`` job (with ``add_tags``)."""
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
        payload: dict[str, str | float | bool | list[str]] = {
            "source_id": str(source_id),
            "add_tags": list(dict.fromkeys(new_tags)),
            "downloadable": downloadable,
        }
        if parse_timeout is not None:
            payload["parse_timeout"] = parse_timeout
        return await enqueue(session, "ingest_source", payload, created_by=reviewer_id)


async def set_licence_file(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    user_id: UUID,
    licence_file_path: str,
) -> None:
    """Attach a licence or permission letter (stored by ``store_licence``) to a source;
    an editor or a reviewer may, audited. The letter never goes to RAGFlow."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await roles_of(session, user_id)
        if not roles & {EDITOR, REVIEWER}:
            raise RoleError("no_content_role")
        row = await _locked(session, source_id)
        previous = row.licence_file_path
        if previous == licence_file_path:
            return
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(licence_file_path=licence_file_path, updated_at=func.now())
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=user_id,
            event="source.licence_file_set",
            metadata={
                "source_id": str(source_id),
                "status": "replaced" if previous else "added",
                "roles": sorted(roles),
            },
        )


def working_days_after(start: date, days: int) -> date:
    """The date ``days`` working days (Monday to Friday) after ``start``."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def takedown_due_on(requested_on: date, *, licence_breach: bool) -> date:
    """10 working days from a valid request; the same day for a licence breach we find
    ourselves (architecture §6.3)."""
    if licence_breach:
        return requested_on
    return working_days_after(requested_on, TAKEDOWN_WORKING_DAYS)


async def record_takedown(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    reference: str,
    requested_on: date,
    licence_breach: bool,
    licence_grounds: bool = False,
) -> date:
    """Put a source on the takedown queue with its due date; returns the due date.

    ``licence_grounds``: the request is on licence grounds (a licence breach we find
    ourselves always is). Recorded for the queue and the audit trail; since owner
    decision 3 (Oct 23, 2026) every withdrawal blanks the stored citation excerpts, so it
    no longer changes what the withdrawal does.
    """
    licence_grounds = licence_grounds or licence_breach
    reference = reference.strip()
    if not reference or len(reference) > MAX_REFERENCE_LENGTH:
        raise RegisterError("bad_reference")
    due = takedown_due_on(requested_on, licence_breach=licence_breach)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        if row.status == "withdrawn":
            raise RegisterError("already_withdrawn")
        before: dict[str, str | int | float | bool | list[str] | None] = {
            "takedown_reference": row.takedown_reference,
            "takedown_due_on": row.takedown_due_on.isoformat() if row.takedown_due_on else None,
            "takedown_licence_grounds": row.takedown_licence_grounds,
        }
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(
                takedown_reference=reference,
                takedown_requested_on=requested_on,
                takedown_due_on=due,
                takedown_licence_grounds=licence_grounds,
                updated_at=func.now(),
            )
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=reviewer_id,
            event="source.takedown_recorded",
            metadata={
                "source_id": str(source_id),
                "before": before,
                "after": {
                    "takedown_reference": reference,
                    "takedown_due_on": due.isoformat(),
                    "takedown_licence_grounds": licence_grounds,
                },
                "roles": sorted(roles),
            },
        )
    return due


@dataclass(frozen=True)
class TakedownItem:
    source_id: UUID
    status: str
    reference: str
    requested_on: date
    due_on: date
    title: str = ""
    licence_grounds: bool = False

    def working_days_left(self, today: date) -> int:
        """Working days until the due date; negative when overdue."""
        if today == self.due_on:
            return 0
        step = 1 if self.due_on > today else -1
        days, current = 0, today
        while current != self.due_on:
            current += timedelta(days=step)
            if current.weekday() < 5:
                days += step
        return days


async def takedown_queue(session: AsyncSession) -> list[TakedownItem]:
    """Sources with a takedown request that are not withdrawn yet, soonest due first."""
    rows = await session.execute(
        select(
            Source.id,
            Source.status,
            Source.takedown_reference,
            Source.takedown_requested_on,
            Source.takedown_due_on,
            Source.title,
            Source.takedown_licence_grounds,
        )
        .where(Source.takedown_due_on.is_not(None), Source.status != "withdrawn")
        .order_by(Source.takedown_due_on, Source.created_at)
    )
    return [
        TakedownItem(
            r.id,
            r.status,
            r.takedown_reference,
            r.takedown_requested_on,
            r.takedown_due_on,
            r.title,
            r.takedown_licence_grounds,
        )
        for r in rows
    ]


async def request_withdrawal(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    reviewer_id: UUID,
    *,
    reason: str,
) -> UUID:
    """A reviewer withdraws a source: records the reason and enqueues the
    ``withdraw_source`` job, which removes it everywhere (``app.content.withdraw``).
    A paused source is withdrawn the same way, with the full cascade (P2A-01)."""
    note = _note(reason, required=True)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        if row.status not in ("ingested", "failed", "paused"):
            raise RegisterError("not_withdrawable")
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(withdrawal_reason=note, updated_at=func.now())
        )
        if row.site_id is not None:
            # A crawled page a reviewer withdraws stays out of later crawls (P1b-04).
            await session.execute(
                update(SitePage)
                .where(SitePage.site_id == row.site_id, SitePage.source_id == source_id)
                .values(state="blocked", reason="withdrawn", special_category=None)
            )
        job_id = await enqueue(
            session, "withdraw_source", {"source_id": str(source_id)}, created_by=reviewer_id
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=reviewer_id,
            event="source.withdrawal_requested",
            metadata={
                "source_id": str(source_id),
                "before": {"status": row.status},
                "after": {"status": row.status},
                "roles": sorted(roles),
            },
        )
    return job_id


# P2A-01: pause and resume.


@dataclass(frozen=True)
class PauseResult:
    """What a pause or a resume did: the RAGFlow documents switched, and (pause only)
    the cached answers purged, None when the cache could not be reached."""

    source_id: UUID
    status: Literal["paused", "ingested"]
    documents: int
    cache_entries_purged: int | None = None


async def _synced_mapping(session: AsyncSession, row: Source) -> list[tuple[str, str]]:
    """The source's ``(dataset_id, document_id)`` pairs, sorted by dataset ID.

    Every key must be a synced dataset's ID; a mapping from before the datasets table
    (Phase 0) cannot be switched document by document, so it is refused rather than
    half-paused. The IDs come from the register, never from a request.
    """
    mapping = row.ragflow_document_ids
    if not isinstance(mapping, dict) or not mapping:
        raise RegisterError("no_documents")
    synced = set(
        (
            await session.scalars(
                select(Dataset.ragflow_dataset_id).where(
                    Dataset.ragflow_dataset_id.in_(list(mapping))
                )
            )
        ).all()
    )
    pairs = [(str(k), str(v)) for k, v in mapping.items() if isinstance(v, str)]
    if len(pairs) != len(mapping) or any(k not in synced for k, _ in pairs):
        raise RegisterError("unmapped_document")
    return sorted(pairs)


async def set_enabled_everywhere(
    client: RagflowClient, pairs: Sequence[tuple[str, str]], *, enabled: bool
) -> tuple[RagflowError | None, bool]:
    """Switch every document; on a failure switch back the ones already done.

    Returns the failure (None when all succeeded) and whether switching back failed
    too, which leaves RAGFlow disagreeing with the register (``datasets sync`` reports
    it). No partial state is ever recorded on the row.
    """
    done: list[tuple[str, str]] = []
    for dataset_id, document_id in pairs:
        try:
            await client.set_document_enabled(dataset_id, document_id, enabled=enabled)
        except RagflowError as exc:
            undo_failed = False
            for undo_dataset, undo_document in reversed(done):
                try:
                    await client.set_document_enabled(
                        undo_dataset, undo_document, enabled=not enabled
                    )
                except RagflowError:
                    undo_failed = True
            return exc, undo_failed
        done.append((dataset_id, document_id))
    return None, False


async def _switch(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    source_id: UUID,
    reviewer_id: UUID,
    *,
    pause: bool,
    reason: str | None,
) -> PauseResult:
    before, after = ("ingested", "paused") if pause else ("paused", "ingested")
    action = "pause" if pause else "resume"
    failure: str | None = None
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await _locked(session, source_id)
        if row.status != before:
            raise RegisterError(f"not_{before}")
        pairs = await _synced_mapping(session, row)
        error, undo_failed = await set_enabled_everywhere(client, pairs, enabled=not pause)
        if error is not None:
            failure = f"{action}_undo_failed" if undo_failed else error.error_code
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=reviewer_id,
                event=f"source.{action}_failed",
                metadata={
                    "source_id": str(source_id),
                    "before": {"status": before},
                    "after": {"status": before},
                    "roles": sorted(roles),
                    "error_code": error.error_code,
                    "outcome": "undo_failed" if undo_failed else "undone",
                    "count": len(pairs),
                },
            )
        else:
            values: dict[str, object] = {"status": after, "updated_at": func.now()}
            if pause:
                values |= {
                    "paused_at": func.now(),
                    "paused_by": reviewer_id,
                    "pause_reason": reason,
                }
            else:
                values |= {"paused_at": None, "paused_by": None, "pause_reason": None}
            await session.execute(update(Source).where(Source.id == source_id).values(**values))
            await _audit(
                session,
                reviewer_id,
                f"source.{after if pause else 'resumed'}",
                source_id,
                before,
                after,
                roles=sorted(roles),
                outcome="ok",
                count=len(pairs),
            )
    if failure is not None:
        log("content.source_switch_failed", source_id=str(source_id), error_code=failure)
        raise RegisterError(failure)
    purged: int | None = None
    if pause:
        # The corpus fingerprint changed with the status, so no cache key of any
        # workspace finds the old answers; they are purged as well, so that a cached
        # answer never cites a paused source (P2A-01).
        try:
            purged = await purge_answer_cache(factory, {str(source_id)})
        except Exception:  # the pause stands; the old keys are unreachable anyway
            log("content.cache_purge_failed", source_id=str(source_id), error_code="cache")
    return PauseResult(source_id, "paused" if pause else "ingested", len(pairs), purged)


async def pause(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    source_id: UUID,
    reviewer_id: UUID,
    *,
    reason: str,
) -> PauseResult:
    """``ingested -> paused``: a reviewer takes the source out of retrieval, the library
    and downloads for every tenant (D1), keeping its RAGFlow documents and its stored
    citations (D3).

    Each RAGFlow document of the source is disabled in this call, not in a job. If one
    fails or answers with the wrong status, those already disabled are enabled again,
    the row stays ``ingested`` and the error code is raised (``source.pause_failed`` is
    audited, never ``source.paused``). A pause does not touch the takedown queue.
    """
    note = _note(reason, required=True)
    return await _switch(factory, client, source_id, reviewer_id, pause=True, reason=note)


async def resume(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    source_id: UUID,
    reviewer_id: UUID,
) -> PauseResult:
    """``paused -> ingested``: every RAGFlow document enabled again, no re-parse. A
    failure disables again those already enabled and leaves the row ``paused``."""
    return await _switch(factory, client, source_id, reviewer_id, pause=False, reason=None)
