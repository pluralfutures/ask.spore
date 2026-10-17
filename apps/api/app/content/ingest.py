"""Ingestion (P0-09): one source into the register and into RAGFlow.

``ingest`` creates a ``sources`` row, uploads the file to the dataset of every
given tag, sets the per-type chunking method where the tag overrides it, triggers
parsing, polls to completion, and records the outcome on the row: ``ingested``
with the chunk count and ``{dataset_id: document_id}``, or ``failed`` with the
error. A failed source leaves nothing retrievable behind: the documents it
uploaded are deleted from RAGFlow, so no chunk of a failed source can be cited.

Dataset IDs come only from the ``datasets`` table (``ask-spore datasets sync``).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.fetch import Fetched, tdm_reserved
from app.content.models import Dataset, Source
from app.content.tags import TagConfig
from app.retrieval.ragflow import RUN_DONE, RagflowClient, RagflowDocument, RagflowError

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

Status = Literal["ingested", "failed", "duplicate"]


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


@dataclass(frozen=True)
class IngestResult:
    source_id: UUID
    status: Status
    chunk_count: int = 0
    error_code: str | None = None
    error: str | None = None
    document_ids: dict[str, str] = field(default_factory=dict)


class _Failure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


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
        raise IngestError(
            "tdm_reserved", f"{fetched.url} reserves text-and-data-mining rights; not ingested"
        )
    name = Path(fetched.url.split("?")[0].rstrip("/")).name or "index"
    source_type = TYPE_BY_MEDIA_TYPE.get(fetched.content_type) or TYPE_BY_SUFFIX.get(
        Path(name).suffix.lower()
    )
    if source_type is None:
        raise IngestError("unsupported_type", f"unsupported content type '{fetched.content_type}'")
    if not fetched.content:
        raise IngestError("empty", f"{fetched.url} returned an empty body")
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
            raise _Failure("parse_timeout", "parsing did not finish before the timeout")
        await sleep(poll_interval)
        document = await client.get_document(document.dataset_id, document.id)
    return document


async def ingest(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    metadata: SourceMetadata,
    *,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    parse_timeout: float = PARSE_TIMEOUT_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> IngestResult:
    """Ingest one source. Raises IngestError, before recording anything, on bad input."""
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

    async with factory() as session, session.begin():
        datasets = await _datasets_for(session, tags)
        missing = [tag for tag in tags if tag not in datasets]
        if missing:
            raise IngestError(
                "no_dataset",
                f"no dataset for {', '.join(missing)}; run `ask-spore datasets sync` first",
            )
        duplicate = await session.scalar(
            select(Source.id).where(
                Source.file_sha256 == source.sha256, Source.status == "ingested"
            )
        )
        if duplicate is not None:
            return IngestResult(source_id=duplicate, status="duplicate")
        row = Source(
            type=source.type,
            title=metadata.title.strip(),
            publisher=metadata.publisher.strip(),
            published_on=metadata.published_on,
            canonical_url=metadata.canonical_url,
            licence_basis=metadata.licence_basis.strip(),
            tags=list(tags),
            status="ingesting",
            file_sha256=source.sha256,
        )
        session.add(row)
        await session.flush()
        source_id = row.id

    uploaded: dict[str, str] = {}  # dataset_id -> document_id
    chunk_count = 0
    failure: _Failure | None = None
    try:
        documents: list[RagflowDocument] = []
        name = upload_name(metadata.title, source_id, source.type)
        for tag in tags:
            dataset_id = datasets[tag]
            document = await client.upload_document(dataset_id, name, source.content)
            uploaded[dataset_id] = document.id
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
                raise _Failure("parse_failed", f"{tag}: parse {done.run}: {done.progress_msg}")
            if done.chunk_count == 0:
                raise _Failure("no_chunks", f"{tag}: parsed into 0 chunks")
            chunk_count += done.chunk_count
    except RagflowError as exc:
        failure = _Failure(exc.error_code, str(exc))
    except _Failure as exc:
        failure = exc
    except Exception as exc:  # recorded on the row; never leave it "ingesting"
        failure = _Failure("internal_error", f"unexpected {type(exc).__name__}")

    if failure is not None:
        error = str(failure)
        try:
            for dataset_id, document_id in uploaded.items():
                await client.delete_documents(dataset_id, [document_id])
            uploaded = {}
        except RagflowError as exc:
            error += f"\nclean-up failed, documents left in RAGFlow: {exc}"
        result = IngestResult(
            source_id=source_id,
            status="failed",
            error_code=failure.code,
            error=_short(error),
            document_ids=uploaded,
        )
    else:
        result = IngestResult(
            source_id=source_id, status="ingested", chunk_count=chunk_count, document_ids=uploaded
        )

    async with factory() as session, session.begin():
        await session.execute(
            update(Source)
            .where(Source.id == source_id)
            .values(
                status=result.status,
                chunk_count=result.chunk_count if result.status == "ingested" else None,
                error=result.error,
                ragflow_document_ids=result.document_ids,
                updated_at=func.now(),
            )
        )
    return result
