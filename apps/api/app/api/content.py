"""/api/v1/content: the content operations console (P1b-05, architecture §7.3).

Every route depends on ``require_content_user``: a user of the internal (platform)
tenant, signed in with Authentik, holding at least one content role
(``content_editor``, ``content_reviewer``). A tenant admin or user of any client tenant,
and an internal user without a content role, gets 403 on every route. Each action is
checked for its own role by ``app.content.register`` and ``app.content.sites`` (an
editor proposes and registers sites, a reviewer approves, rejects, retries, withdraws,
records takedowns and changes site settings); a missing role is 403. Every action is
audited there, under the internal tenant.

The console shows register metadata only: never document text beyond the title, never a
chunk. For chunk spot-checks it links to the private RAGFlow UI at its loopback address
(``[ragflow] admin_ui_url``), which an operator opens over an SSH tunnel; RAGFlow itself
is never reached through these routes, except the tag sync, which runs the same
server-side ``datasets sync`` as the CLI. No route takes a dataset or document ID.

Uploads (a proposed file, a licence letter) are multipart forms; nothing about them is
logged but identifiers and codes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.content_schemas import (
    ApproveIn,
    ContentMeOut,
    ContentSourceDetail,
    ContentSourceOut,
    DocumentLink,
    HistoryEntry,
    JobOut,
    JobQueuedOut,
    NoteIn,
    PatternsIn,
    ProposeOut,
    SiteApproveIn,
    SiteCreateIn,
    SiteDetail,
    SiteOut,
    SitePageOut,
    SiteSettingsIn,
    SourceRef,
    TagOut,
    TagSyncOut,
    TakedownIn,
    TakedownOut,
    WithdrawIn,
)
from app.api.deps import request_context
from app.api.schemas import _refuse_control_chars
from app.audit.models import AuditEvent
from app.audit.writer import record
from app.auth.middleware import IDENTITY_KEY
from app.content import register, sites
from app.content.datasets import sync_datasets
from app.content.fetch import (
    MAX_BYTES,
    Connector,
    FetchError,
    Resolver,
    fetch,
    http_client,
    require_http_url,
    resolve_host,
)
from app.content.ingest import TYPE_BY_SUFFIX, IngestError, SourceFile, SourceMetadata, from_fetched
from app.content.jobs import Job
from app.content.models import Dataset, Site, SitePage, Source
from app.content.register import RegisterError
from app.content.roles import EDITOR, REVIEWER, RoleError, roles_of
from app.content.store import StoredFileError, read, store_licence
from app.content.tags import load_tags
from app.core.config import Settings
from app.core.db import tenant_session
from app.core.logging import log
from app.retrieval.ragflow import RagflowClient, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID, User

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
MAX_LIST = 500
MAX_PAGES_SHOWN = 2000
MAX_HISTORY = 200
MAX_JOBS = 20
MAX_ERROR_SHOWN = 500
MAX_LICENCE_BYTES = 20 * 1024 * 1024
LICENCE_EXTENSIONS = frozenset({"pdf", "docx", "txt", "eml", "png", "jpg", "jpeg"})
# Register and site codes that mean "bad input" (422); the others are state conflicts.
INPUT_CODES = frozenset(
    {
        "note_required",
        "note_too_long",
        "bad_reference",
        "bad_pattern",
        "too_many_patterns",
        "bad_schedule",
        "bad_max_pages",
        "bad_url",
        "no_tag",
        "unknown_tag",
        "missing_metadata",
        "replace_or_keep_both",
        "not_a_replacement_candidate",
        "replacement_choice_required",
        "already_being_replaced",
    }
)


@dataclass(frozen=True)
class ContentUser:
    user_id: UUID
    roles: frozenset[str]


async def require_content_user(request: Request) -> ContentUser:
    """401 without a session; 403 unless an Authentik-signed-in internal user with a
    content role."""
    context = request_context(request)
    identity = getattr(request.state, IDENTITY_KEY, None)
    if identity is None:
        log("content.refused", error_code="not_oidc")
        raise FORBIDDEN
    if identity.service:
        # P1b-15 a: the eval harness's credential never opens the content console.
        log("content.refused", error_code="service_identity")
        raise FORBIDDEN
    if context.tenant_id != INTERNAL_TENANT_ID:
        log("content.refused", tenant_id=str(context.tenant_id), error_code="not_platform")
        raise FORBIDDEN
    async with tenant_session(request.app.state.db_factory, INTERNAL_TENANT_ID) as session:
        roles = await roles_of(session, context.user_id)
    if not roles:
        log("content.refused", user_id=str(context.user_id), error_code="no_content_role")
        raise FORBIDDEN
    return ContentUser(context.user_id, roles)


async def content_session(
    request: Request, _: ContentUser = Depends(require_content_user)
) -> AsyncIterator[AsyncSession]:
    """A read transaction scoped to the internal tenant (its users and audit trail; the
    register, sites and jobs are shared tables outside tenant RLS)."""
    async with tenant_session(request.app.state.db_factory, INTERNAL_TENANT_ID) as session:
        yield session


router = APIRouter(prefix="/api/v1/content", dependencies=[Depends(require_content_user)])


def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_factory
    return factory


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _resolver(request: Request) -> Resolver:
    resolve: Resolver = getattr(request.app.state, "content_resolve", resolve_host)
    return resolve


def _refused(exc: RegisterError | RoleError | IngestError | FetchError) -> HTTPException:
    if isinstance(exc, RoleError):
        log("content.refused", error_code=exc.code)
        return FORBIDDEN
    if exc.code in ("no_source", "no_site"):
        return NOT_FOUND
    if isinstance(exc, IngestError | FetchError) or exc.code in INPUT_CODES:
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code)
    return HTTPException(status.HTTP_409_CONFLICT, detail=exc.code)


def _ragflow_url(settings: Settings, dataset_id: str, document_id: str | None = None) -> str | None:
    """The loopback RAGFlow UI page of a dataset or document; None when not configured."""
    ragflow = settings.models.ragflow
    if ragflow.admin_ui_url is None:
        return None
    path = ragflow.admin_ui_document_path if document_id else ragflow.admin_ui_dataset_path
    return ragflow.admin_ui_url.rstrip("/") + path.format(
        dataset_id=dataset_id, document_id=document_id or ""
    )


async def _emails(session: AsyncSession, ids: Sequence[UUID | None]) -> dict[UUID, str]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.email).where(User.tenant_id == INTERNAL_TENANT_ID, User.id.in_(wanted))
    )
    return {r.id: r.email for r in rows}


def _text_field(value: str | None, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    value = value.strip()
    try:
        _refuse_control_chars(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="bad_text") from None
    if len(value) > limit:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="too_long")
    return value or None


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    if upload.size is not None and upload.size > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="too_large")
    content = bytearray()
    while chunk := await upload.read(1024 * 1024):
        content += chunk
        if len(content) > limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="too_large")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty")
    return bytes(content)


def _extension(upload: UploadFile) -> str:
    return Path(upload.filename or "").suffix.lower().lstrip(".")


async def _licence(request: Request, upload: UploadFile) -> str:
    extension = _extension(upload)
    if extension not in LICENCE_EXTENSIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="bad_licence_file")
    content = await _read_upload(upload, MAX_LICENCE_BYTES)
    root = _settings(request).models.files.content_root
    try:
        return store_licence(root, content, extension)
    except (OSError, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="bad_licence_file"
        ) from None


# --- who am I ----------------------------------------------------------------------------


@router.get("/me", response_model=ContentMeOut)
async def content_me(
    request: Request, user: ContentUser = Depends(require_content_user)
) -> ContentMeOut:
    return ContentMeOut(
        roles=sorted(user.roles), ragflow_ui_url=_settings(request).models.ragflow.admin_ui_url
    )


# --- the register ------------------------------------------------------------------------


def _replacement_flag() -> Any:
    """``possible_replacement`` for a list query: a proposal at the canonical link of an
    ingested source that is not a crawled page (owner decision 4), unless it replaces one
    with the same title (``supersedes_id`` set at proposal, owner decision 3)."""
    other = Source.__table__.alias("other")
    return (
        select(func.count())
        .select_from(other)
        .where(
            other.c.canonical_url == Source.canonical_url,
            other.c.status == "ingested",
            other.c.site_id.is_(None),
            other.c.id != Source.id,
        )
        .correlate(Source)
        .scalar_subquery()
    )


def _source_out(row: Any, flag: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "publisher": row.publisher,
        "published_on": row.published_on,
        "canonical_url": row.canonical_url,
        "licence_basis": row.licence_basis,
        "tags": list(row.tags),
        "status": row.status,
        "downloadable": row.downloadable,
        "site_id": row.site_id,
        "takedown_due_on": row.takedown_due_on,
        "possible_replacement": flag,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/sources", response_model=list[ContentSourceOut])
async def list_sources(
    session: AsyncSession = Depends(content_session),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    tag: str | None = Query(default=None, max_length=100),
    type_filter: str | None = Query(default=None, alias="type", max_length=20),
    publisher: str | None = Query(default=None, max_length=200),
    site_id: UUID | None = None,
) -> list[ContentSourceOut]:
    """The register, newest change first, filtered by status, tag, type and publisher
    (a case-insensitive part of the name); at most 500 rows."""
    flag = _replacement_flag()
    query = select(Source, flag.label("candidates")).order_by(Source.updated_at.desc(), Source.id)
    if status_filter:
        query = query.where(Source.status == status_filter)
    if tag:
        query = query.where(Source.tags.contains([tag]))
    if type_filter:
        query = query.where(Source.type == type_filter)
    if publisher:
        pattern = publisher.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Source.publisher.ilike(f"%{pattern}%", escape="\\"))
    if site_id:
        query = query.where(Source.site_id == site_id)
    rows = (await session.execute(query.limit(MAX_LIST))).all()
    return [
        ContentSourceOut(
            **_source_out(
                row.Source,
                row.Source.status == "proposed"
                and row.candidates > 0
                and row.Source.supersedes_id is None,
            )
        )
        for row in rows
    ]


async def _refs(session: AsyncSession, ids: Sequence[UUID]) -> list[SourceRef]:
    if not ids:
        return []
    rows = await session.execute(
        select(Source.id, Source.title, Source.publisher, Source.status).where(
            Source.id.in_(list(ids))
        )
    )
    by_id = {
        r.id: SourceRef(id=r.id, title=r.title, publisher=r.publisher, status=r.status)
        for r in rows
    }
    return [by_id[i] for i in ids if i in by_id]


async def _jobs(session: AsyncSession, key: str, value: str) -> list[JobOut]:
    rows = await session.scalars(
        select(Job)
        .where(Job.payload[key].astext == value)
        .order_by(Job.created_at.desc())
        .limit(MAX_JOBS)
    )
    return [
        JobOut(
            id=j.id,
            type=j.type,
            status=j.status,
            error_code=j.error_code,
            attempts=j.attempts,
            created_at=j.created_at,
            finished_at=j.finished_at,
        )
        for j in rows
    ]


async def _history(session: AsyncSession, source_id: UUID) -> list[HistoryEntry]:
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == INTERNAL_TENANT_ID,
                AuditEvent.metadata_["source_id"].astext == str(source_id),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(MAX_HISTORY)
        )
    ).all()
    emails = await _emails(session, [e.actor_user_id for e in events])

    def status_of(change: object) -> str | None:
        value = change.get("status") if isinstance(change, dict) else None
        return value if isinstance(value, str) else None

    return [
        HistoryEntry(
            event=e.event,
            at=e.created_at,
            actor=emails.get(e.actor_user_id) if e.actor_user_id else None,
            before=status_of(e.metadata_.get("before")),
            after=status_of(e.metadata_.get("after")),
            method=e.metadata_.get("method")
            if isinstance(e.metadata_.get("method"), str)
            else None,
        )
        for e in events
    ]


@router.get("/sources/{source_id}", response_model=ContentSourceDetail)
async def source_detail(
    source_id: UUID, request: Request, session: AsyncSession = Depends(content_session)
) -> ContentSourceDetail:
    row = await session.get(Source, source_id)
    if row is None:
        raise NOT_FOUND
    settings = _settings(request)
    candidates = (
        await register.replacement_candidates(session, row.canonical_url, exclude=row.id)
        if row.status == "proposed" and row.site_id is None and row.supersedes_id is None
        else []
    )
    datasets = {d.ragflow_dataset_id: d.tag for d in (await session.scalars(select(Dataset))).all()}
    documents = [
        DocumentLink(
            tag=datasets.get(dataset_id, "?"),
            dataset_id=dataset_id,
            document_id=str(document_id),
            ragflow_url=_ragflow_url(settings, dataset_id, str(document_id)),
        )
        for dataset_id, document_id in sorted((row.ragflow_document_ids or {}).items())
    ]
    emails = await _emails(session, [row.proposed_by, row.approved_by])
    takedown = None
    if row.takedown_reference and row.takedown_requested_on and row.takedown_due_on:
        item = register.TakedownItem(
            row.id,
            row.status,
            row.takedown_reference,
            row.takedown_requested_on,
            row.takedown_due_on,
            row.title,
            row.takedown_licence_grounds,
        )
        takedown = _takedown_out(item)
    supersedes = await _refs(session, [row.supersedes_id] if row.supersedes_id else [])
    return ContentSourceDetail(
        **_source_out(row, bool(candidates)),
        review_note=row.review_note,
        review_date=row.review_date,
        proposed_by=emails.get(row.proposed_by) if row.proposed_by else None,
        approved_by=emails.get(row.approved_by) if row.approved_by else None,
        approved_at=row.approved_at,
        withdrawn_at=row.withdrawn_at,
        withdrawal_reason=row.withdrawal_reason,
        chunk_count=row.chunk_count,
        error=(row.error or "")[:MAX_ERROR_SHOWN] or None,
        licence_file=row.licence_file_path is not None,
        stored=row.stored_path is not None,
        fetched_at=row.fetched_at,
        supersedes=supersedes[0] if supersedes else None,
        possible_replacements=await _refs(session, candidates),
        takedown=takedown,
        documents=documents,
        history=await _history(session, row.id),
        jobs=await _jobs(session, "source_id", str(row.id)),
    )


@router.get("/sources/{source_id}/licence")
async def source_licence(
    source_id: UUID, request: Request, session: AsyncSession = Depends(content_session)
) -> Response:
    """The licence or permission letter on file, as a download."""
    path = await session.scalar(select(Source.licence_file_path).where(Source.id == source_id))
    if path is None:
        raise NOT_FOUND
    sha256 = Path(path).stem
    try:
        content = read(_settings(request).models.files.content_root, path, sha256)
    except StoredFileError as exc:
        log("content.licence_unavailable", source_id=str(source_id), error_code=exc.code)
        raise NOT_FOUND from None
    extension = Path(path).suffix
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="licence-{source_id}{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    response_model=ProposeOut,
    responses={200: {"model": ProposeOut, "description": "already in the register"}},
)
async def propose_source(
    request: Request,
    response: Response,
    user: ContentUser = Depends(require_content_user),
    title: str = Form(min_length=1, max_length=500),
    publisher: str = Form(min_length=1, max_length=300),
    licence_basis: str = Form(min_length=1, max_length=300),
    tags: list[str] = Form(min_length=1),
    published_on: date | None = Form(default=None),
    canonical_url: str | None = Form(default=None, max_length=1000),
    downloadable: bool = Form(default=False),
    url: str | None = Form(default=None, max_length=1000),
    file: UploadFile | None = File(default=None),
    licence_file: UploadFile | None = File(default=None),
) -> ProposeOut:
    """An editor proposes a file (upload) or a URL, with the manifest's metadata. The
    licence basis is always required; a licence or permission letter may be attached,
    downloadable or not (decision 10, Oct 22, 2026: no letter is required for now)."""
    if EDITOR not in user.roles:
        log("content.refused", user_id=str(user.user_id), error_code="not_content_editor")
        raise FORBIDDEN
    if (file is None) == (url is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file_or_url")
    title_, publisher_ = _text_field(title), _text_field(publisher, limit=300)
    licence_ = _text_field(licence_basis, limit=300)
    canonical = _text_field(canonical_url, limit=1000)
    tag_list = [t for t in (_text_field(t, limit=100) for t in tags) if t]
    if canonical is not None:
        try:
            require_http_url(canonical)
        except FetchError as exc:
            raise _refused(exc) from None
    if file is not None:
        source_type = TYPE_BY_SUFFIX.get(Path(file.filename or "").suffix.lower())
        if source_type is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unsupported_type")
        content = await _read_upload(file, MAX_BYTES)
        source = SourceFile(
            f"upload{Path(file.filename or '').suffix.lower()}", source_type, content
        )
    elif url is not None:
        resolve = _resolver(request)
        connect: Connector | None = getattr(request.app.state, "content_connect", None)
        try:
            async with http_client(resolve, connect) as http:
                source = from_fetched(await fetch(http, url.strip()))
        except (FetchError, IngestError) as exc:
            raise _refused(exc) from None
        canonical = canonical or url.strip()
    licence_path = await _licence(request, licence_file) if licence_file is not None else None
    metadata = SourceMetadata(
        tags=tuple(tag_list),
        title=title_ or "",
        publisher=publisher_ or "",
        licence_basis=licence_ or "",
        published_on=published_on,
        canonical_url=canonical,
        downloadable=downloadable,
    )
    factory = _factory(request)
    try:
        submission = await register.propose(
            factory,
            load_tags(_settings(request).config_dir),
            source,
            metadata,
            content_root=_settings(request).models.files.content_root,
            proposer_id=user.user_id,
            licence_file_path=licence_path,
        )
        if submission.outcome != "proposed" and licence_path is not None:
            await register.set_licence_file(
                factory, submission.source_id, user.user_id, licence_path
            )
    except (IngestError, RoleError, RegisterError) as exc:
        raise _refused(exc) from None
    if submission.outcome != "proposed":
        response.status_code = status.HTTP_200_OK
    log(
        "content.proposed",
        user_id=str(user.user_id),
        source_id=str(submission.source_id),
        status=submission.outcome,
    )
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        replacements = await _refs(session, list(submission.possible_replacements))
        replaces = await _refs(session, [submission.replaces] if submission.replaces else [])
    return ProposeOut(
        source_id=submission.source_id,
        outcome=submission.outcome,
        status=submission.status,
        possible_replacements=replacements,
        replaces=replaces[0] if replaces else None,
    )


@router.put("/sources/{source_id}/licence", status_code=status.HTTP_204_NO_CONTENT)
async def attach_licence(
    source_id: UUID,
    request: Request,
    user: ContentUser = Depends(require_content_user),
    licence_file: UploadFile = File(),
) -> Response:
    if not user.roles & {EDITOR, REVIEWER}:
        raise FORBIDDEN
    path = await _licence(request, licence_file)
    try:
        await register.set_licence_file(_factory(request), source_id, user.user_id, path)
    except (RoleError, RegisterError) as exc:
        raise _refused(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _decide(action: Any) -> Any:
    try:
        return await action
    except (RoleError, RegisterError, IngestError, FetchError) as exc:
        raise _refused(exc) from None


@router.post("/sources/{source_id}/approve", response_model=JobQueuedOut)
async def approve_source(
    source_id: UUID,
    body: ApproveIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> JobQueuedOut:
    """A reviewer approves a proposal, which queues its ingestion. For a possible
    replacement the reviewer names the source it replaces, or keeps both."""
    job_id = await _decide(
        register.approve(
            _factory(request),
            source_id,
            user.user_id,
            note=body.note,
            replaces=body.replaces,
            keep_both=body.keep_both,
        )
    )
    return JobQueuedOut(job_id=job_id)


@router.post("/sources/{source_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_source(
    source_id: UUID,
    body: NoteIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> Response:
    await _decide(register.reject(_factory(request), source_id, user.user_id, note=body.note))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sources/{source_id}/retry", response_model=JobQueuedOut)
async def retry_source(
    source_id: UUID, request: Request, user: ContentUser = Depends(require_content_user)
) -> JobQueuedOut:
    job_id = await _decide(register.retry(_factory(request), source_id, user.user_id))
    return JobQueuedOut(job_id=job_id)


@router.post("/sources/{source_id}/withdraw", response_model=JobQueuedOut)
async def withdraw_source(
    source_id: UUID,
    body: WithdrawIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> JobQueuedOut:
    job_id = await _decide(
        register.request_withdrawal(_factory(request), source_id, user.user_id, reason=body.reason)
    )
    return JobQueuedOut(job_id=job_id)


@router.post("/sources/{source_id}/takedown", response_model=TakedownOut)
async def record_takedown(
    source_id: UUID,
    body: TakedownIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> TakedownOut:
    if body.requested_on > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="requested_in_future")
    factory = _factory(request)
    await _decide(
        register.record_takedown(
            factory,
            source_id,
            user.user_id,
            reference=body.reference,
            requested_on=body.requested_on,
            licence_breach=body.licence_breach,
            licence_grounds=body.licence_grounds,
        )
    )
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        queue = await register.takedown_queue(session)
    (item,) = [i for i in queue if i.source_id == source_id]
    return _takedown_out(item)


def _takedown_out(item: register.TakedownItem) -> TakedownOut:
    return TakedownOut(
        source_id=item.source_id,
        title=item.title,
        status=item.status,
        reference=item.reference,
        requested_on=item.requested_on,
        due_on=item.due_on,
        working_days_left=item.working_days_left(date.today()),
        licence_grounds=item.licence_grounds,
    )


@router.get("/takedowns", response_model=list[TakedownOut])
async def takedowns(session: AsyncSession = Depends(content_session)) -> list[TakedownOut]:
    """The takedown queue, soonest due first, with the SLA timer in working days."""
    return [_takedown_out(item) for item in await register.takedown_queue(session)]


# --- sites -------------------------------------------------------------------------------


def _site_out(site: Site, blocked: int) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "start_url": site.start_url,
        "host": site.host,
        "publisher": site.publisher,
        "licence_basis": site.licence_basis,
        "tags": list(site.tags),
        "status": site.status,
        "schedule": site.schedule,
        "max_pages": site.max_pages,
        "allow_decision": site.allow_decision,
        "allow_checked_at": site.allow_checked_at,
        "last_crawl_at": site.last_crawl_at,
        "last_crawl_status": site.last_crawl_status,
        "next_crawl_at": site.next_crawl_at,
        "page_count": site.page_count,
        "blocked_count": blocked,
    }


def _blocked_count() -> Any:
    return (
        select(func.count())
        .select_from(SitePage)
        .where(SitePage.site_id == Site.id, SitePage.state == "blocked")
        .correlate(Site)
        .scalar_subquery()
    )


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(session: AsyncSession = Depends(content_session)) -> list[SiteOut]:
    rows = await session.execute(
        select(Site, _blocked_count().label("blocked")).order_by(Site.name, Site.id)
    )
    return [SiteOut(**_site_out(r.Site, r.blocked)) for r in rows]


@router.post("/sites", status_code=status.HTTP_201_CREATED, response_model=SiteOut)
async def create_site(
    body: SiteCreateIn, request: Request, user: ContentUser = Depends(require_content_user)
) -> SiteOut:
    """An editor registers a site for a reviewer to approve."""
    factory = _factory(request)
    spec = sites.SiteSpec(
        start_url=body.start_url,
        name=body.name,
        publisher=body.publisher,
        licence_basis=body.licence_basis,
        tags=tuple(body.tags),
        allow_patterns=tuple(body.allow_patterns),
        deny_patterns=tuple(body.deny_patterns),
        schedule=body.schedule,
        max_pages=body.max_pages,
    )
    site_id, created = await _decide(
        sites.register_site(
            factory,
            load_tags(_settings(request).config_dir),
            spec,
            proposer_id=user.user_id,
            resolve=_resolver(request),
        )
    )
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="site_exists")
    async with factory() as session:
        site = await session.get(Site, site_id)
    if site is None:
        raise NOT_FOUND
    return SiteOut(**_site_out(site, 0))


@router.get("/sites/{site_id}", response_model=SiteDetail)
async def site_detail(
    site_id: UUID, session: AsyncSession = Depends(content_session)
) -> SiteDetail:
    """The site, its settings and every page a crawl met (blocked ones with the reason)."""
    site = await session.get(Site, site_id)
    if site is None:
        raise NOT_FOUND
    pages = (
        await session.scalars(
            select(SitePage)
            .where(SitePage.site_id == site_id)
            .order_by((SitePage.state == "live").asc(), SitePage.state, SitePage.url)
            .limit(MAX_PAGES_SHOWN)
        )
    ).all()
    blocked = sum(1 for p in pages if p.state == "blocked")
    emails = await _emails(session, [site.proposed_by, site.approved_by])
    return SiteDetail(
        **_site_out(site, blocked),
        allow_patterns=list(site.allow_patterns),
        deny_patterns=list(site.deny_patterns),
        special_category_allow=list(site.special_category_allow),
        review_note=site.review_note,
        proposed_by=emails.get(site.proposed_by) if site.proposed_by else None,
        approved_by=emails.get(site.approved_by) if site.approved_by else None,
        approved_at=site.approved_at,
        pages=[
            SitePageOut(
                url=p.url,
                state=p.state,
                reason=p.reason,
                special_category=p.special_category,
                source_id=p.source_id,
                published_on=p.published_on,
                fetched_at=p.fetched_at,
            )
            for p in pages
        ],
        jobs=await _jobs(session, "site_id", str(site_id)),
    )


@router.post("/sites/{site_id}/approve", response_model=JobQueuedOut)
async def approve_site(
    site_id: UUID,
    body: SiteApproveIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> JobQueuedOut:
    job_id = await _decide(
        sites.approve_site(_factory(request), site_id, user.user_id, note=body.note)
    )
    return JobQueuedOut(job_id=job_id)


@router.post("/sites/{site_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_site(
    site_id: UUID, body: NoteIn, request: Request, user: ContentUser = Depends(require_content_user)
) -> Response:
    await _decide(sites.reject_site(_factory(request), site_id, user.user_id, note=body.note))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/sites/{site_id}/settings", status_code=status.HTTP_204_NO_CONTENT)
async def site_settings(
    site_id: UUID,
    body: SiteSettingsIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> Response:
    settings = sites.SiteSettings(
        tuple(body.allow_patterns), tuple(body.deny_patterns), body.schedule, body.max_pages
    )
    await _decide(sites.update_site(_factory(request), site_id, user.user_id, settings))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/sites/{site_id}/special-category-allow", status_code=status.HTTP_204_NO_CONTENT)
async def site_whitelist(
    site_id: UUID,
    body: PatternsIn,
    request: Request,
    user: ContentUser = Depends(require_content_user),
) -> Response:
    await _decide(
        sites.set_special_category_allow(_factory(request), site_id, user.user_id, body.patterns)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sites/{site_id}/crawl", response_model=JobQueuedOut)
async def crawl_now(
    site_id: UUID, request: Request, user: ContentUser = Depends(require_content_user)
) -> JobQueuedOut:
    job_id = await _decide(sites.request_crawl(_factory(request), site_id, user.user_id))
    return JobQueuedOut(job_id=job_id)


# --- tags --------------------------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    request: Request, session: AsyncSession = Depends(content_session)
) -> list[TagOut]:
    """The tags of ``config/tags.toml`` (read-only here) and their datasets."""
    settings = _settings(request)
    config = load_tags(settings.config_dir)
    datasets = {d.tag: d.ragflow_dataset_id for d in (await session.scalars(select(Dataset))).all()}
    counts: dict[str, int] = dict(
        (
            await session.execute(
                select(func.unnest(Source.tags).label("tag"), func.count())
                .where(Source.status == "ingested")
                .group_by("tag")
            )
        ).all()
    )
    return [
        TagOut(
            tag=tag,
            chunk_method=cfg.chunk_method,
            chunk_method_by_type={str(k): str(v) for k, v in cfg.chunk_method_by_type.items()},
            dataset_id=datasets.get(tag),
            ragflow_url=_ragflow_url(settings, datasets[tag]) if tag in datasets else None,
            sources=int(counts.get(tag, 0)),
        )
        for tag, cfg in sorted(config.items())
    ]


@router.post("/tags/sync", response_model=list[TagSyncOut])
async def sync_tags(
    request: Request, user: ContentUser = Depends(require_content_user)
) -> list[TagSyncOut]:
    """A reviewer runs ``datasets sync``: a dataset for every tag in ``config/tags.toml``
    (created or adopted in RAGFlow, server-side), audited. The file is not edited here."""
    if REVIEWER not in user.roles:
        log("content.refused", user_id=str(user.user_id), error_code="not_content_reviewer")
        raise FORBIDDEN
    settings = _settings(request)
    tags = load_tags(settings.config_dir)
    factory = _factory(request)
    client_factory = getattr(request.app.state, "content_ragflow", RagflowClient.from_settings)
    try:
        async with (
            client_factory(settings) as client,
            tenant_session(factory, INTERNAL_TENANT_ID) as session,
        ):
            results = await sync_datasets(
                session, client, tags, settings.models.ragflow.embedding_model
            )
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=user.user_id,
                event="content.datasets_synced",
                metadata={
                    "count": len(results),
                    "status": "failed" if any(r.failed for r in results) else "ok",
                    "roles": sorted(user.roles),
                },
            )
    except RagflowError as exc:
        log("content.tags_sync_failed", error_code=exc.error_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ragflow_unavailable") from None
    for result in results:
        log("content.tag_synced", tag=result.tag, status=result.status)
    return [TagSyncOut(tag=r.tag, status=r.status, dataset_id=r.dataset_id) for r in results]
