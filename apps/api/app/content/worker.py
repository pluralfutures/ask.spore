"""The ingestion worker (P1b-02): ``ask-spore worker``, a Compose service of its own.

It runs the same image as the API and polls ``jobs`` (``app.content.jobs``), one job
at a time, so RAGFlow sees at most one ingestion from us at once (its own task
concurrency stays as tuned in Phase 1a, findings §9). Each job type has a handler:

- ``ingest_source``: ``app.content.ingest.ingest_source`` for an approved source, or
  ``add_tags`` when the payload names tags to add;
- ``withdraw_source``: ``app.content.withdraw.withdraw_source`` (P1b-03), which also
  purges the tenants' answer caches;
- ``crawl_site``: ``app.content.sitecrawl.crawl_site`` (P1b-04), one crawl of one
  approved site, at the worker's per-host rate limit; between jobs the worker queues
  the crawls that are due (``app.content.sites.schedule_due_crawls``).

A job of a type without a handler fails with ``unsupported_job_type``.

A handler returns an error code or None; transient RAGFlow failures (timeouts,
unreachable, 5xx) are retried with backoff until the job's last attempt. While a
handler works, the worker renews the job's lease; when the worker is stopped, the job
goes back to the queue without counting the attempt. Log lines carry the job's ID,
type, status, attempts and error code only.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.crawler import HostLimiter
from app.content.fetch import Resolver, http_client, resolve_host
from app.content.ingest import (
    PARSE_TIMEOUT_SECONDS,
    add_tags,
    ingest_source,
)
from app.content.ingest import (
    POLL_INTERVAL_SECONDS as PARSE_POLL_SECONDS,
)
from app.content.jobs import LEASE_SECONDS, ClaimedJob, claim, finish, release, renew
from app.content.sitecrawl import crawl_site
from app.content.tags import TagConfig
from app.content.withdraw import withdraw_source
from app.core.logging import log
from app.retrieval.ragflow import RagflowClient

POLL_INTERVAL_SECONDS: Final = 5.0
# RAGFlow failures worth another attempt: the service was briefly unavailable.
RETRYABLE: Final = frozenset(
    {
        "ragflow_timeout",
        "ragflow_unreachable",
        "ragflow_500",
        "ragflow_502",
        "ragflow_503",
        "ragflow_504",
    }
)


@dataclass(frozen=True)
class Outcome:
    error_code: str | None = None
    retry: bool = False
    source_id: UUID | None = None
    site_id: UUID | None = None


Handler = Callable[[ClaimedJob], Awaitable[Outcome]]


@dataclass(frozen=True)
class Context:
    factory: async_sessionmaker[AsyncSession]
    client: RagflowClient
    tags: Mapping[str, TagConfig]
    content_root: Path
    parse_poll_interval: float = PARSE_POLL_SECONDS
    # Crawling (P1b-04): a fresh HTTP client per crawl, one rate limiter per worker.
    http: Callable[[], httpx.AsyncClient] = http_client
    limiter: HostLimiter = field(default_factory=HostLimiter)
    resolve: Resolver = resolve_host


def _source_id(job: ClaimedJob) -> UUID | None:
    try:
        return UUID(str(job.payload["source_id"]))
    except (KeyError, ValueError):
        return None


def ingest_handler(ctx: Context) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        source_id = _source_id(job)
        if source_id is None:
            return Outcome("bad_payload")
        parse_timeout = float(job.payload.get("parse_timeout") or PARSE_TIMEOUT_SECONDS)
        retryable = frozenset() if job.last_attempt else RETRYABLE
        add = job.payload.get("add_tags")
        if add:
            result = await add_tags(
                ctx.factory,
                ctx.client,
                ctx.tags,
                source_id,
                [str(tag) for tag in add],
                downloadable=bool(job.payload.get("downloadable")),
                content_root=ctx.content_root,
                actor_user_id=None,
                parse_timeout=parse_timeout,
                poll_interval=ctx.parse_poll_interval,
            )
        else:
            result = await ingest_source(
                ctx.factory,
                ctx.client,
                ctx.tags,
                source_id,
                content_root=ctx.content_root,
                parse_timeout=parse_timeout,
                poll_interval=ctx.parse_poll_interval,
                retryable=retryable,
            )
        if result.status in ("ingested", "retagged", "duplicate"):
            return Outcome(source_id=source_id)
        code = result.error_code or "failed"
        return Outcome(code, retry=code in retryable, source_id=source_id)

    return handle


def withdraw_handler(ctx: Context) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        source_id = _source_id(job)
        if source_id is None:
            return Outcome("bad_payload")
        result = await withdraw_source(
            ctx.factory, ctx.client, source_id, content_root=ctx.content_root
        )
        if result.status == "withdrawn":
            return Outcome(source_id=source_id)
        code = result.error_code or "failed"
        retry = code in RETRYABLE or code == "cache_unavailable"
        return Outcome(code, retry=retry, source_id=source_id)

    return handle


def crawl_handler(ctx: Context) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        try:
            site_id = UUID(str(job.payload["site_id"]))
        except (KeyError, ValueError):
            return Outcome("bad_payload")
        async with ctx.http() as http:
            result = await crawl_site(
                ctx.factory,
                site_id,
                http=http,
                content_root=ctx.content_root,
                limiter=ctx.limiter,
                resolve=ctx.resolve,
            )
        # A site that disallows us or reserves its rights is a recorded decision, not a
        # failure; an unreachable site waits for its next scheduled crawl.
        return Outcome(result.error_code, site_id=site_id)

    return handle


def handlers(ctx: Context) -> dict[str, Handler]:
    return {
        "ingest_source": ingest_handler(ctx),
        "withdraw_source": withdraw_handler(ctx),
        "crawl_site": crawl_handler(ctx),
    }


async def _keep_lease(
    factory: async_sessionmaker[AsyncSession], job: ClaimedJob, lease_seconds: int
) -> None:
    while True:
        await asyncio.sleep(lease_seconds / 3)
        await renew(factory, job.id, lease_seconds)


async def run_once(
    factory: async_sessionmaker[AsyncSession],
    registry: Mapping[str, Handler],
    *,
    lease_seconds: int = LEASE_SECONDS,
) -> bool:
    """Claim and run one job; False when there was none to run."""
    job = await claim(factory, lease_seconds=lease_seconds)
    if job is None:
        return False
    started = time.monotonic()
    handler = registry.get(job.type)
    keeper = asyncio.create_task(_keep_lease(factory, job, lease_seconds))
    try:
        if handler is None:
            outcome = Outcome("unsupported_job_type")
        else:
            try:
                outcome = await handler(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # the job fails with a code; the worker goes on
                outcome = Outcome("internal_error")
    except asyncio.CancelledError:
        keeper.cancel()
        await release(factory, job)
        log("job.released", job_id=str(job.id), job_type=job.type, status="queued")
        raise
    finally:
        keeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keeper
    status = await finish(factory, job, error_code=outcome.error_code, retry=outcome.retry)
    log(
        "job.finished",
        level="info" if outcome.error_code is None else "error",
        job_id=str(job.id),
        job_type=job.type,
        source_id=str(outcome.source_id) if outcome.source_id else None,
        site_id=str(outcome.site_id) if outcome.site_id else None,
        status=status,
        attempts=job.attempts,
        error_code=outcome.error_code,
        latency_ms=round((time.monotonic() - started) * 1000),
    )
    return True


async def run(
    factory: async_sessionmaker[AsyncSession],
    registry: Mapping[str, Handler],
    *,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    stop: asyncio.Event | None = None,
    once: bool = False,
    tick: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Run jobs one at a time until ``stop`` is set (or, with ``once``, the queue is empty).

    ``tick`` runs before each claim (the crawl scheduler)."""
    stop = stop or asyncio.Event()
    log("worker.started", status="running")
    while not stop.is_set():
        try:
            if tick is not None:
                await tick()
            ran = await run_once(factory, registry)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # e.g. the database is restarting: wait and poll again
            log("worker.poll_failed", level="error", exception=type(exc).__name__)
            ran = False
        if ran:
            continue
        if once:
            break
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), poll_interval)
    log("worker.stopped", status="stopped")
