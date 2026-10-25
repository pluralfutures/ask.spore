"""Ingestion (P0-09, P1b-01): one approved source into RAGFlow.

A source is proposed and approved first (``app.content.register``). ``ingest_source``
then reads the file staged under ``[files] content_root``, uploads it to the dataset
of every tag of the row, sets the per-type chunking method where the tag overrides
it, triggers parsing, polls to completion, and records the outcome on the row:
``ingested`` with the chunk count and ``{dataset_id: document_id}``, or ``failed``
with the error. A failed source leaves nothing retrievable behind: the documents it
uploaded are deleted from RAGFlow, so no chunk of a failed source can be cited. A
source that is not ``approved`` is refused without any call to RAGFlow.

Dataset IDs come only from the ``datasets`` table (``ask-spore datasets sync``).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable, Container, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.content.fetch import Fetched, tdm_reserved
from app.content.jobs import enqueue
from app.content.models import Dataset, SitePage, Source
from app.content.store import StoredFileError, read, relative_path
from app.content.tags import TagConfig
from app.core.db import tenant_session
from app.retrieval.ragflow import RUN_DONE, RagflowClient, RagflowDocument, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID

TYPE_BY_SUFFIX: Mapping[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
}
TYPE_BY_MEDIA_TYPE: Mapping[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/markdown": "markdown",
}
SUFFIX_BY_TYPE: Mapping[str, str] = {
    "pdf": ".pdf",
    "docx": ".docx",
    "pptx": ".pptx",
    "html": ".html",
    "markdown": ".md",
}
POLL_INTERVAL_SECONDS = 3.0
PARSE_TIMEOUT_SECONDS = 1800.0
MAX_ERROR_LENGTH = 2000
PAGE_GONE_REASON = "crawled page no longer on the site when its ingestion finished"

# proposed and retag_pending wait for a reviewer (P1b-01); refused: not approved;
# queued: approved, with an ingest_source job for the worker (P1b-02).
Status = Literal[
    "ingested",
    "failed",
    "duplicate",
    "retagged",
    "refused",
    "proposed",
    "retag_pending",
    "queued",
]


class IngestError(ValueError):
    """The request cannot be ingested as given; nothing was recorded."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SourceFile:
    filename: str
    type: str  # one of app.content.models.SOURCE_TYPES
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class SourceMetadata:
    tags: tuple[str, ...]
    title: str
    publisher: str
    licence_basis: str
    published_on: date | None = None
    canonical_url: str | None = None
    # P1a-14: the licence gate for downloads; set per source, false unless stated.
    downloadable: bool = False


@dataclass(frozen=True)
class IngestResult:
    source_id: UUID
    status: Status
    chunk_count: int = 0
    error_code: str | None = None
    error: str | None = None
    document_ids: dict[str, str] = field(default_factory=dict)
    tags_added: tuple[str, ...] = ()  # retagged only
    job_id: UUID | None = None  # queued, and after waiting for the job
    seconds: float = 0.0  # the job's run time, after waiting for it


class _Failure(Exception):
    """An ingestion failure. Its message, which becomes ``IngestResult.error`` and the
    source row's ``error`` (shown in the content console), is the code, optionally
    followed by context of our own: ``<code>`` or ``<code>: <context>``.

    P2A-13 (Phase 1c independent review, item 3): the context is built from our own
    codes, tags and names only. A ``RagflowError`` contributes its ``error_code``, never
    its text (the detail is RAGFlow's own message), and a parse no ``progress_msg``.
    """

    def __init__(self, code: str, context: str | None = None) -> None:
        self.code = code
        self.context = context
        super().__init__(f"{code}: {context}" if context else code)


def load_path(path: Path) -> SourceFile:
    source_type = TYPE_BY_SUFFIX.get(path.suffix.lower())
    if source_type is None:
        raise IngestError(
            "unsupported_type",
            f"unsupported file type '{path.suffix}'; expected one of "
            + ", ".join(sorted(TYPE_BY_SUFFIX)),
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise IngestError("unreadable", f"cannot read {path}: {exc.strerror}") from None
    if not content:
        raise IngestError("empty", f"{path} is empty")
    return SourceFile(filename=path.name, type=source_type, content=content)


def from_fetched(fetched: Fetched) -> SourceFile:
    """A fetched URL as a source file; refuses content with a TDM reservation."""
    if tdm_reserved(fetched.headers, fetched.content, fetched.is_html):
        # The message never carries the URL: it reaches the CLI's exit text (P1c-04 rule).
        raise IngestError(
            "tdm_reserved", "the page reserves text-and-data-mining rights; not ingested"
        )
    name = Path(fetched.url.split("?")[0].rstrip("/")).name or "index"
    source_type = TYPE_BY_MEDIA_TYPE.get(fetched.content_type) or TYPE_BY_SUFFIX.get(
        Path(name).suffix.lower()
    )
    if source_type is None:
        raise IngestError("unsupported_type", f"unsupported content type '{fetched.content_type}'")
    if not fetched.content:
        raise IngestError("empty", "the page returned an empty body")
    stem = Path(name).stem or "index"
    return SourceFile(stem + SUFFIX_BY_TYPE[source_type], source_type, fetched.content)


def upload_name(title: str, source_id: UUID, source_type: str) -> str:
    """File name shown in the RAGFlow UI: readable, and unique per source."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "source"
    return f"{slug}-{source_id.hex[:8]}{SUFFIX_BY_TYPE[source_type]}"


def _short(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_ERROR_LENGTH else "…" + text[-MAX_ERROR_LENGTH:]


async def _datasets_for(session: AsyncSession, tags: Sequence[str]) -> dict[str, str]:
    rows = (await session.scalars(select(Dataset).where(Dataset.tag.in_(tags)))).all()
    return {row.tag: row.ragflow_dataset_id for row in rows}


async def _wait(
    client: RagflowClient,
    document: RagflowDocument,
    *,
    poll_interval: float,
    deadline: float,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float],
) -> RagflowDocument:
    while not document.finished:
        if clock() >= deadline:
            raise _Failure("parse_timeout")
        await sleep(poll_interval)
        document = await client.get_document(document.dataset_id, document.id)
    return document


async def _upload_and_parse(
    client: RagflowClient,
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    tags: Sequence[str],
    datasets: Mapping[str, str],
    name: str,
    *,
    poll_interval: float,
    parse_timeout: float,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float],
    on_upload: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[dict[str, str], int, _Failure | None]:
    """Upload ``source`` to each tag's dataset and parse it to completion.

    Returns ``{dataset_id: document_id}``, the chunk count and the failure, if any. On
    failure the documents uploaded here are deleted; the mapping returned then holds
    only those whose deletion failed (named in the failure's message). ``on_upload``
    is told the mapping after each upload, so an interrupted run can be cleaned up.
    """
    uploaded: dict[str, str] = {}  # dataset_id -> document_id
    chunk_count = 0
    failure: _Failure | None = None
    try:
        documents: list[RagflowDocument] = []
        for tag in tags:
            dataset_id = datasets[tag]
            document = await client.upload_document(dataset_id, name, source.content)
            uploaded[dataset_id] = document.id
            if on_upload is not None:
                await on_upload(dict(uploaded))
            method = tags_config[tag].chunk_method_for(source.type)
            if method != tags_config[tag].chunk_method:
                await client.set_document_chunk_method(dataset_id, document.id, method)
            await client.start_parse(dataset_id, [document.id])
            documents.append(document)
        deadline = clock() + parse_timeout
        for tag, document in zip(tags, documents, strict=True):
            done = await _wait(
                client,
                document,
                poll_interval=poll_interval,
                deadline=deadline,
                sleep=sleep,
                clock=clock,
            )
            if done.run != RUN_DONE:
                # RAGFlow's progress_msg is its own text: never kept (P2A-13). The run
                # is one of our TERMINAL_RUNS constants (FAIL or CANCEL) here.
                raise _Failure("parse_failed", f"{tag} {done.run}")
            if done.chunk_count == 0:
                raise _Failure("no_chunks", tag)
            chunk_count += done.chunk_count
    except RagflowError as exc:
        failure = _Failure(exc.error_code)
    except _Failure as exc:
        failure = exc
    except Exception as exc:  # recorded on the row; never leave it "ingesting"
        failure = _Failure("internal_error", type(exc).__name__)

    if failure is None:
        return uploaded, chunk_count, None
    try:
        for dataset_id, document_id in uploaded.items():
            await client.delete_documents(dataset_id, [document_id])
        uploaded = {}
    except RagflowError as exc:
        left = f"clean-up failed ({exc.error_code}), documents left in RAGFlow"
        context = f"{failure.context}; {left}" if failure.context else left
        return uploaded, 0, _Failure(failure.code, context)
    return uploaded, 0, failure


async def _staged_content(content_root: Path, sha256: str, source_type: str) -> bytes:
    try:
        return read(content_root, relative_path(sha256, source_type), sha256)
    except StoredFileError as exc:
        raise _Failure(f"staged_{exc.code}") from None


async def ingest_source(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    tags_config: Mapping[str, TagConfig],
    source_id: UUID,
    *,
    content_root: Path,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    parse_timeout: float = PARSE_TIMEOUT_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    retryable: Container[str] = frozenset(),
) -> IngestResult:
    """Ingest one approved source into the datasets of its tags.

    ``refused`` (nothing touched, no call to RAGFlow) unless the row is ``approved``;
    otherwise the row ends ``ingested`` or ``failed``, audited under the internal tenant.
    A failure whose code is in ``retryable`` leaves the row ``approved`` (the job queue
    tries again). Each upload is recorded on the row at once, so a run that was cut off
    (worker stopped) leaves a mapping the next run deletes from RAGFlow before uploading.
    """
    async with factory() as session:
        row = (
            await session.execute(
                select(
                    Source.status,
                    Source.type,
                    Source.title,
                    Source.tags,
                    Source.file_sha256,
                    Source.ragflow_document_ids,
                    Source.supersedes_id,
                    Source.site_id,
                ).where(Source.id == source_id)
            )
        ).first()
    if row is None:
        return IngestResult(source_id=source_id, status="refused", error_code="no_source")
    if row.status != "approved":
        return IngestResult(source_id=source_id, status="refused", error_code="not_approved")

    async def record_uploads(mapping: dict[str, str]) -> None:
        async with factory() as session, session.begin():
            await session.execute(
                update(Source)
                .where(Source.id == source_id, Source.status == "approved")
                .values(ragflow_document_ids=mapping, updated_at=func.now())
            )

    tags = tuple(row.tags)
    uploaded: dict[str, str] = {}
    chunk_count = 0
    failure: _Failure | None = None
    try:
        leftover: dict[str, str] = dict(row.ragflow_document_ids or {})
        if leftover:
            uploaded = dict(leftover)
            try:
                for dataset_id, document_id in leftover.items():
                    await client.delete_documents(dataset_id, [document_id])
                    del uploaded[dataset_id]
            except RagflowError as exc:
                raise _Failure(exc.error_code, "clean-up of an interrupted run") from None
            await record_uploads({})
        if row.file_sha256 is None:
            raise _Failure("no_file")
        content = await _staged_content(content_root, row.file_sha256, row.type)
        async with factory() as session:
            datasets = await _datasets_for(session, tags)
        missing = [tag for tag in tags if tag not in datasets or tag not in tags_config]
        if missing:
            raise _Failure("no_dataset", ", ".join(missing))
        uploaded, chunk_count, failure = await _upload_and_parse(
            client,
            tags_config,
            SourceFile(upload_name(row.title, source_id, row.type), row.type, content),
            tags,
            datasets,
            upload_name(row.title, source_id, row.type),
            poll_interval=poll_interval,
            parse_timeout=parse_timeout,
            sleep=sleep,
            clock=clock,
            on_upload=record_uploads,
        )
    except _Failure as exc:
        failure = exc

    if failure is not None and failure.code in retryable:
        # The row stays approved, mapping only what is left in RAGFlow; no audit event
        # until the source's state changes.
        await record_uploads(uploaded)
        return IngestResult(
            source_id=source_id,
            status="failed",
            error_code=failure.code,
            error=_short(str(failure)),
            document_ids=uploaded,
        )

    if failure is not None:
        result = IngestResult(
            source_id=source_id,
            status="failed",
            error_code=failure.code,
            error=_short(str(failure)),
            document_ids=uploaded,
        )
    else:
        result = IngestResult(
            source_id=source_id, status="ingested", chunk_count=chunk_count, document_ids=uploaded
        )
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        await session.execute(
            update(Source)
            .where(Source.id == source_id, Source.status == "approved")
            .values(
                status=result.status,
                chunk_count=result.chunk_count if result.status == "ingested" else None,
                error=result.error,
                ragflow_document_ids=result.document_ids,
                updated_at=func.now(),
            )
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event=f"source.{result.status}",
            metadata={
                "source_id": str(source_id),
                "before": {"status": "approved"},
                "after": {"status": result.status},
                "error_code": result.error_code,
            },
        )
        if result.status == "ingested" and row.supersedes_id is not None:
            # P1b-03: the new version is live; withdraw the one it replaces.
            await enqueue(
                session,
                "withdraw_source",
                {"source_id": str(row.supersedes_id)},
                created_by=None,
            )
        if result.status == "ingested" and row.site_id is not None:
            # P1b-04: a crawled page that left the site (gone, out of scope, a TDM
            # reservation) while it waited for ingestion is withdrawn at once.
            live = await session.scalar(
                select(func.count())
                .select_from(SitePage)
                .where(SitePage.source_id == source_id, SitePage.state == "live")
            )
            if not live:
                await session.execute(
                    update(Source)
                    .where(Source.id == source_id)
                    .values(withdrawal_reason=PAGE_GONE_REASON)
                )
                await enqueue(
                    session, "withdraw_source", {"source_id": str(source_id)}, created_by=None
                )
    return result


async def _map_retag(
    factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    mapping: Mapping[str, str],
    datasets: Container[str],
) -> None:
    """Map exactly ``mapping`` among ``datasets`` (the re-tag's) on an ingested row."""
    async with factory() as session, session.begin():
        current = await session.scalar(
            select(Source.ragflow_document_ids)
            .where(Source.id == source_id, Source.status == "ingested")
            .with_for_update()
        )
        if current is None:
            return
        kept = {k: v for k, v in current.items() if k not in datasets}
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(ragflow_document_ids={**kept, **mapping}, updated_at=func.now())
        )


async def _clean_unfinished_retag(
    factory: async_sessionmaker[AsyncSession], client: RagflowClient, source_id: UUID
) -> None:
    """Delete the documents an interrupted re-tag left mapped on the row: those in the
    dataset of a synced tag the source does not hold. Keys that are not a synced
    dataset's ID (mappings from before Phase 1a) are never touched."""
    async with factory() as session:
        row = (
            await session.execute(
                select(Source.tags, Source.ragflow_document_ids).where(Source.id == source_id)
            )
        ).one()
        other = set(
            (
                await session.scalars(
                    select(Dataset.ragflow_dataset_id).where(Dataset.tag.not_in(list(row.tags)))
                )
            ).all()
        )
    leftover = {k: str(v) for k, v in (row.ragflow_document_ids or {}).items() if k in other}
    if not leftover:
        return
    remaining = dict(leftover)
    try:
        for dataset_id, document_id in leftover.items():
            await client.delete_documents(dataset_id, [document_id])
            del remaining[dataset_id]
    except RagflowError as exc:
        raise _Failure(exc.error_code, "clean-up of an interrupted re-tag") from None
    finally:
        await _map_retag(factory, source_id, remaining, set(leftover))


async def add_tags(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    tags_config: Mapping[str, TagConfig],
    source_id: UUID,
    new_tags: Sequence[str],
    *,
    downloadable: bool,
    content_root: Path,
    actor_user_id: UUID | None = None,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    parse_timeout: float = PARSE_TIMEOUT_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> IngestResult:
    """Link an ingested source into the datasets of ``new_tags`` (P1a-04).

    RAGFlow cannot attach an existing document to a second dataset, so the file is
    uploaded and parsed again in each new dataset, as on first ingestion. On failure
    the new documents are deleted and the source keeps its status, tags and other
    datasets. On success the source gains the tags and documents, and the row's
    ``downloadable`` from the request (the owner's declaration), audited under the
    platform tenant. A source that is not ``ingested`` is refused.

    Each new upload is mapped on the row at once, as on first ingestion (P1c-14): a
    document in the dataset of a tag the row does not hold yet belongs to an
    unfinished re-tag. A run cut off by a stopped worker therefore leaves a mapping
    the next re-tag of the source deletes from RAGFlow before uploading (and a
    withdrawal deletes with the rest); a failed run unmaps what it deleted and keeps
    mapped only the documents whose deletion failed.
    """
    async with factory() as session:
        row = (
            await session.execute(
                select(
                    Source.status, Source.type, Source.title, Source.tags, Source.file_sha256
                ).where(Source.id == source_id)
            )
        ).first()
    if row is None or row.status != "ingested" or row.file_sha256 is None:
        code = "no_source" if row is None else "not_ingested"
        return IngestResult(source_id=source_id, status="refused", error_code=code)
    try:
        await _clean_unfinished_retag(factory, client, source_id)
    except _Failure as exc:
        return IngestResult(
            source_id=source_id, status="failed", error_code=exc.code, error=_short(str(exc))
        )
    new_tags = tuple(tag for tag in dict.fromkeys(new_tags) if tag not in row.tags)
    if not new_tags:
        return IngestResult(source_id=source_id, status="duplicate")

    try:
        content = await _staged_content(content_root, row.file_sha256, row.type)
        async with factory() as session:
            datasets = await _datasets_for(session, new_tags)
        missing = [tag for tag in new_tags if tag not in datasets or tag not in tags_config]
        if missing:
            raise _Failure("no_dataset", ", ".join(missing))
    except _Failure as exc:
        return IngestResult(
            source_id=source_id, status="failed", error_code=exc.code, error=_short(str(exc))
        )
    name = upload_name(row.title, source_id, row.type)
    new_datasets = {datasets[tag] for tag in new_tags}

    async def record_uploads(mapping: dict[str, str]) -> None:
        await _map_retag(factory, source_id, mapping, new_datasets)

    uploaded, chunk_count, failure = await _upload_and_parse(
        client,
        tags_config,
        SourceFile(name, row.type, content),
        new_tags,
        datasets,
        name,
        poll_interval=poll_interval,
        parse_timeout=parse_timeout,
        sleep=sleep,
        clock=clock,
        on_upload=record_uploads,
    )
    if failure is not None:
        # Documents whose clean-up failed stay mapped (and named in the error), so the
        # next re-tag or a withdrawal deletes them; the tags are not the source's.
        await record_uploads(uploaded)
        return IngestResult(
            source_id=source_id,
            status="failed",
            error_code=failure.code,
            error=_short(str(failure)),
            document_ids=uploaded,
        )

    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        current = (
            await session.execute(
                select(Source.tags, Source.ragflow_document_ids, Source.downloadable)
                .where(Source.id == source_id)
                .with_for_update()
            )
        ).one()
        tags = list(dict.fromkeys([*current.tags, *new_tags]))
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(
                tags=tags,
                ragflow_document_ids={**current.ragflow_document_ids, **uploaded},
                chunk_count=func.coalesce(Source.chunk_count, 0) + chunk_count,
                downloadable=downloadable,
                updated_at=func.now(),
            )
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=actor_user_id,
            event="ingest.source_retagged",
            metadata={
                "source_id": str(source_id),
                "before": {"tag_ids": list(current.tags), "downloadable": current.downloadable},
                "after": {"tag_ids": tags, "downloadable": downloadable},
            },
        )
    return IngestResult(
        source_id=source_id,
        status="retagged",
        chunk_count=chunk_count,
        document_ids=uploaded,
        tags_added=new_tags,
    )
