"""One file from the command line through the register (P1b-01): propose, then approve
and ingest when a reviewer is named.

The CLIs (``ingest``, ``crawl``, ``ingest-manifest``) call ``submit`` per file. Without a
reviewer the file stays a proposal (or a pending re-tag) for a reviewer to decide; with
``--approve-as`` the reviewer approves it in the same run, audited, and it is ingested.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.ingest import (
    PARSE_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    IngestResult,
    SourceFile,
    SourceMetadata,
    add_tags,
    ingest_source,
)
from app.content.register import approve, approve_retag, propose, retry
from app.content.tags import TagConfig
from app.retrieval.ragflow import RagflowClient


async def submit(
    factory: async_sessionmaker[AsyncSession],
    client: RagflowClient,
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    metadata: SourceMetadata,
    *,
    content_root: Path,
    proposer_id: UUID | None,
    reviewer_id: UUID | None,
    parse_timeout: float = PARSE_TIMEOUT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> IngestResult:
    """Propose ``source``; with ``reviewer_id``, approve and ingest it.

    Raises IngestError on bad input (nothing recorded), RoleError when a named user lacks
    the role. The result's status is ``proposed`` or ``retag_pending`` while a reviewer
    has to decide, else what ingestion did.
    """
    submission = await propose(
        factory, tags_config, source, metadata, content_root=content_root, proposer_id=proposer_id
    )
    source_id = submission.source_id
    if submission.outcome == "duplicate":
        return IngestResult(source_id=source_id, status="duplicate")
    if submission.outcome == "taken_down":
        return IngestResult(source_id=source_id, status="failed", error_code="taken_down")
    if reviewer_id is None:
        if submission.outcome == "retag":
            return IngestResult(source_id=source_id, status="retag_pending")
        if submission.status == "failed":
            return IngestResult(source_id=source_id, status="failed", error_code="needs_retry")
        if submission.status == "proposed":
            return IngestResult(source_id=source_id, status="proposed")
    elif submission.outcome == "retag":
        await approve_retag(factory, source_id, reviewer_id, submission.new_tags)
        return await add_tags(
            factory,
            client,
            tags_config,
            source_id,
            submission.new_tags,
            downloadable=metadata.downloadable,
            content_root=content_root,
            actor_user_id=reviewer_id,
            parse_timeout=parse_timeout,
            poll_interval=poll_interval,
            sleep=sleep,
            clock=clock,
        )
    elif submission.status == "proposed":
        await approve(factory, source_id, reviewer_id)
    elif submission.status == "failed":
        await retry(factory, source_id, reviewer_id)
    return await ingest_source(
        factory,
        client,
        tags_config,
        source_id,
        content_root=content_root,
        parse_timeout=parse_timeout,
        poll_interval=poll_interval,
        sleep=sleep,
        clock=clock,
    )
