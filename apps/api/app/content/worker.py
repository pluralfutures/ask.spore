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
  the crawls that are due (``app.content.sites.schedule_due_crawls``);
- ``import_crawl`` (P2SR01-03): ``app.content.uploadcrawl.import_crawl``, the import of
  one released uploaded crawl; its payload names the upload only;
- ``send_mail`` (P1b-11): ``app.mail.jobs.send_mail``, when the worker was given a mail
  context; mail failures that may pass (timeouts, 429, 5xx) are retried with backoff;
- ``purge_retention`` (P1b-14): ``app.tenancy.purge.purge_retention``, every tenant's
  expired history, revoked sessions and old download records; between jobs the worker
  queues one a day (``app.tenancy.purge.schedule_purge``).

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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.crawler import HostLimiter
from app.content.fetch import Connector, Resolver, resolve_host
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
from app.content.uploadcrawl import import_crawl
from app.content.withdraw import withdraw_source
from app.core.logging import log
from app.mail.jobs import MailContext, send_mail
from app.retrieval.ragflow import RagflowClient
from app.tenancy.purge import purge_retention

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
    # Crawling (P1b-04): a fresh pinned HTTP client per crawl (P1b-18), one rate
    # limiter per worker. ``connect`` replaces the network for tests only.
    connect: Connector | None = None
    limiter: HostLimiter = field(default_factory=HostLimiter)
    resolve: Resolver = resolve_host
    mail: MailContext | None = None  # P1b-11: send_mail jobs
    downloads_retention_days: int = 90  # P1b-14: [retention] downloads_days


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
        result = await crawl_site(
            ctx.factory,
            site_id,
            content_root=ctx.content_root,
            limiter=ctx.limiter,
            resolve=ctx.resolve,
            connect=ctx.connect,
        )
        # A site that disallows us or reserves its rights is a recorded decision, not a
        # failure; an unreachable site waits for its next scheduled crawl.
        return Outcome(result.error_code, site_id=site_id)

    return handle


def import_handler(ctx: Context) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        try:
            upload_id = UUID(str(job.payload["upload_id"]))
        except (KeyError, ValueError):
            return Outcome("bad_payload")
        result = await import_crawl(ctx.factory, upload_id, content_root=ctx.content_root)
        # A failed import is recorded on the upload; it is not retried (a reviewer
        # releases a new upload instead).
        return Outcome(result.error_code, site_id=result.site_id)

    return handle


def mail_handler(mail: MailContext) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        result = await send_mail(mail, job)
        # Metadata only: the job, its template and outcome; never the address or text.
        log(
            "mail.job",
            level="info" if result.error_code is None else "warning",
            job_id=str(job.id),
            template=str(job.payload.get("template", ""))[:64],
            status="sent" if result.error_code is None else "failed",
            error_code=result.error_code,
        )
        return Outcome(result.error_code, retry=result.retry)

    return handle


def purge_handler(ctx: Context) -> Handler:
    async def handle(job: ClaimedJob) -> Outcome:
        purged = await purge_retention(ctx.factory, downloads_days=ctx.downloads_retention_days)
        # Counts per tenant and table only (P1b-14).
        for tenant in purged:
            for table, count in tenant.counts.as_dict().items():
                if count:
                    log(
                        "retention.purged",
                        job_id=str(job.id),
                        tenant_id=str(tenant.tenant_id),
                        table=table,
                        count=count,
                    )
        log(
            "retention.purge_finished",
            job_id=str(job.id),
            status="purged",
            count=sum(t.counts.total for t in purged),
        )
        return Outcome()

    return handle


def handlers(ctx: Context) -> dict[str, Handler]:
    registry = {
        "ingest_source": ingest_handler(ctx),
        "withdraw_source": withdraw_handler(ctx),
        "crawl_site": crawl_handler(ctx),
        "import_crawl": import_handler(ctx),
        "purge_retention": purge_handler(ctx),
    }
    if ctx.mail is not None:
        registry["send_mail"] = mail_handler(ctx.mail)
    return registry


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
