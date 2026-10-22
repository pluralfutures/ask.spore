"""One file from the command line through the register (P1b-01, P1b-02): propose, and
approve when a reviewer is named, which queues it for the worker. A site (P1b-04) goes
the same way through ``submit_site``: registered, approved by the named reviewer, and
crawled by the worker; ``settle_site`` waits for the crawl and hands back the page
ingestions it queued.

The CLIs (``ingest``, ``crawl``, ``ingest-manifest``) call ``submit`` per file. Without a
reviewer the file stays a proposal (or a pending re-tag) for a reviewer to decide; with
``--approve-as`` the reviewer approves it in the same run, audited, and the approval
enqueues an ``ingest_source`` job. The CLI then waits for the jobs with ``--wait``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from sqlalchemy import Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.fetch import Resolver, resolve_host
from app.content.ingest import IngestResult, SourceFile, SourceMetadata
from app.content.jobs import Job, wait_for
from app.content.models import Site, Source
from app.content.register import RegisterError, approve, approve_retag, propose, retry
from app.content.sites import SiteSpec, approve_site, register_site, request_crawl
from app.content.tags import TagConfig


async def _active_job(factory: async_sessionmaker[AsyncSession], source_id: UUID) -> UUID | None:
    async with factory() as session:
        job_id: UUID | None = await session.scalar(
            select(Job.id)
            .where(
                Job.type == "ingest_source",
                Job.status.in_(("queued", "running")),
                Job.payload["source_id"].astext == str(source_id),
            )
            .order_by(Job.created_at)
            .limit(1)
        )
    return job_id


async def submit(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    source: SourceFile,
    metadata: SourceMetadata,
    *,
    content_root: Path,
    proposer_id: UUID | None,
    reviewer_id: UUID | None,
    parse_timeout: float | None = None,
) -> IngestResult:
    """Propose ``source``; with ``reviewer_id``, approve it (which queues it).

    Raises IngestError on bad input (nothing recorded), RoleError when a named user lacks
    the role. The result's status is ``proposed`` or ``retag_pending`` while a reviewer
    has to decide (``proposed`` with ``possible_replacement`` when the file sits at the
    canonical link of an ingested source: the reviewer chooses replace or keep both),
    ``queued`` (with the job) once approved, ``duplicate`` when there is nothing to do,
    or ``failed`` (``taken_down``; ``needs_retry`` for a failed source without a
    reviewer).
    """
    submission = await propose(
        factory, tags_config, source, metadata, content_root=content_root, proposer_id=proposer_id
    )
    source_id = submission.source_id
    if submission.outcome == "duplicate":
        return IngestResult(source_id=source_id, status="duplicate")
    if submission.outcome == "taken_down":
        return IngestResult(source_id=source_id, status="failed", error_code="taken_down")
    if submission.outcome == "retag":
        if reviewer_id is None:
            return IngestResult(source_id=source_id, status="retag_pending")
        job_id = await approve_retag(
            factory,
            source_id,
            reviewer_id,
            submission.new_tags,
            downloadable=metadata.downloadable,
            parse_timeout=parse_timeout,
        )
        return IngestResult(
            source_id=source_id, status="queued", job_id=job_id, tags_added=submission.new_tags
        )
    if submission.status == "approved":  # queued by an earlier run
        return IngestResult(
            source_id=source_id, status="queued", job_id=await _active_job(factory, source_id)
        )
    if reviewer_id is None:
        if submission.status == "failed":
            return IngestResult(source_id=source_id, status="failed", error_code="needs_retry")
        return IngestResult(source_id=source_id, status="proposed")
    if submission.status == "failed":
        job_id = await retry(factory, source_id, reviewer_id, parse_timeout=parse_timeout)
        return IngestResult(source_id=source_id, status="queued", job_id=job_id)
    try:
        job_id = await approve(factory, source_id, reviewer_id, parse_timeout=parse_timeout)
    except RegisterError as exc:
        if exc.code != "replacement_choice_required":
            raise
        # Owner decision 4 (Oct 22, 2026): a file at the canonical link of an ingested
        # source waits for the reviewer's choice, replace or keep both, in the console
        # (or ``sources approve --replace | --keep-both``); the CLI never decides it.
        return IngestResult(
            source_id=source_id, status="proposed", error_code="possible_replacement"
        )
    return IngestResult(source_id=source_id, status="queued", job_id=job_id)


async def settle(
    factory: async_sessionmaker[AsyncSession],
    results: Sequence[IngestResult],
    *,
    poll_interval: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[IngestResult]:
    """Wait for the jobs of ``queued`` results and return what they did (``--wait``).

    A finished ingestion reports the source's chunk count; a finished re-tag reports
    ``retagged``; a failed job its error code. Other results are returned unchanged.
    """
    job_ids = [r.job_id for r in results if r.status == "queued" and r.job_id is not None]
    if not job_ids:
        return list(results)
    states = await wait_for(factory, job_ids, poll_interval=poll_interval, sleep=sleep, clock=clock)
    async with factory() as session:
        rows = await session.execute(
            select(Source.id, Source.chunk_count).where(
                Source.id.in_([r.source_id for r in results])
            )
        )
        chunks = {row.id: row.chunk_count for row in rows}
    settled: list[IngestResult] = []
    for result in results:
        state = states.get(result.job_id) if result.job_id is not None else None
        if (
            result.status != "queued"
            or state is None
            or state.status not in ("succeeded", "failed")
        ):
            settled.append(result)
        elif state.status == "failed":
            settled.append(
                replace(result, status="failed", error_code=state.error_code, seconds=state.seconds)
            )
        elif result.tags_added:
            settled.append(replace(result, status="retagged", seconds=state.seconds))
        else:
            count = chunks.get(result.source_id) or 0
            settled.append(
                replace(result, status="ingested", chunk_count=count, seconds=state.seconds)
            )
    return settled


@dataclass(frozen=True)
class SiteSubmission:
    """What ``submit_site`` did with a site: ``proposed`` (waits for a reviewer),
    ``queued`` (a crawl job), ``ok`` (approved earlier, nothing queued) or ``failed``
    (``error_code`` ``site_rejected``)."""

    site_id: UUID
    status: str
    job_id: UUID | None = None
    error_code: str | None = None


async def submit_site(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    spec: SiteSpec,
    *,
    proposer_id: UUID | None,
    reviewer_id: UUID | None,
    resolve: Resolver = resolve_host,
) -> SiteSubmission:
    """Register a site (P1b-04); with ``reviewer_id``, approve it or, when it is approved
    already, ask for a crawl now. The crawl itself is the worker's ``crawl_site`` job.

    Raises RegisterError or RoleError (nothing recorded), FetchError for a start URL
    that is not public.
    """
    site_id, _ = await register_site(
        factory, tags_config, spec, proposer_id=proposer_id, resolve=resolve
    )
    async with factory() as session:
        status = await session.scalar(select(Site.status).where(Site.id == site_id))
    if status == "rejected":
        return SiteSubmission(site_id, "failed", error_code="site_rejected")
    if reviewer_id is None:
        return SiteSubmission(site_id, "proposed" if status == "proposed" else "ok")
    if status == "proposed":
        job_id = await approve_site(factory, site_id, reviewer_id)
    else:
        job_id = await request_crawl(factory, site_id, reviewer_id)
    return SiteSubmission(site_id, "queued", job_id)


async def settle_site(
    factory: async_sessionmaker[AsyncSession],
    submission: SiteSubmission,
    *,
    poll_interval: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, list[IngestResult]]:
    """Wait for a queued crawl; returns ``ok`` and the page ingestions it queued, finished
    or not (for ``settle``), or the crawl job's error code and no pages."""
    if submission.job_id is None:
        return submission.error_code or "ok", []
    states = await wait_for(
        factory, [submission.job_id], poll_interval=poll_interval, sleep=sleep, clock=clock
    )
    state = states[submission.job_id]
    if state.status != "succeeded":
        return state.error_code or "failed", []
    async with factory() as session:
        crawl_started = await session.scalar(
            select(Job.created_at).where(Job.id == submission.job_id)
        )
        rows = await session.execute(
            select(Source.id, Job.id.label("job_id"))
            .join(
                Job,
                (Job.payload["source_id"].astext == func.cast(Source.id, Text))
                & (Job.type == "ingest_source")
                & (Job.created_at >= crawl_started),
            )
            .where(Source.site_id == submission.site_id)
            .order_by(Job.created_at)
        )
        return "ok", [IngestResult(source_id=r.id, status="queued", job_id=r.job_id) for r in rows]
