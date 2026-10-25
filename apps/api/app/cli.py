"""``ask-spore`` command line for content operations (P0-08 to P0-11, P1b-01) and for
granting the operator role (P1a-03, ``operators grant|revoke``) and the content roles
(P1b-01, ``content-roles grant|revoke``), both as the schema owner.

Every file goes through the source register (P1b-01): it is proposed, and ingested only
once a reviewer approves it, either in the same run (``--approve-as <reviewer email>``)
or later (``sources approve``).

Runs where the API runs (inside the Compose network, e.g.
``docker compose -f infra/compose.dev.yml run --rm api ask-spore datasets sync``):
it needs the same configuration and secrets, and reaches RAGFlow on the internal
network. Output is metadata-only JSON log lines via app.core.logging.log();
the exit status is non-zero when anything failed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.authentik import oidc_services
from app.auth.provider import ProviderError
from app.consent.notices import ConsentNoticeTick
from app.content import worker
from app.content.datasets import dataset_counts, status_mismatches, sync_datasets
from app.content.fetch import FetchError, fetch, http_client
from app.content.ingest import (
    IngestError,
    IngestResult,
    SourceFile,
    SourceMetadata,
    from_fetched,
    load_path,
)
from app.content.jobs import enqueue, wait_for
from app.content.manifest import (
    ManifestError,
    ManifestRow,
    RowOutcome,
    load_manifest,
    row_outcome,
    run_manifest,
    write_summary,
)
from app.content.register import (
    RegisterError,
    approve,
    record_takedown,
    reject,
    request_withdrawal,
    retry,
)
from app.content.roles import RoleError, grant_role, revoke_role, user_by_email
from app.content.sites import SiteSpec, restore_page, schedule_due_crawls, withdraw_site
from app.content.submit import settle, settle_site, submit, submit_site
from app.content.tags import TagConfig, load_tags
from app.core import cache
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
from app.core.mail import create_mail_sender
from app.mail.jobs import MailContext
from app.operator.grants import create_eval_identity, grant_operator, revoke_operator
from app.retrieval.ragflow import RagflowClient
from app.tenancy.purge import purge_retention, schedule_purge
from app.tenancy.termination import TerminationError, terminate_tenant


async def _datasets_counts() -> int:
    settings = get_settings()
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        async with (
            RagflowClient.from_settings(settings) as client,
            session_factory(engine)() as session,
            session.begin(),
        ):
            counts = await dataset_counts(session, client)
    finally:
        await engine.dispose()
    for item in counts:
        log(
            "datasets.counts",
            level="info" if item.documents is not None else "error",
            tag=item.tag,
            dataset_id=item.dataset_id,
            status="ok" if item.documents is not None else "missing",
            count=item.documents,
            chunk_count=item.chunks,
        )
    return 0 if all(item.documents is not None for item in counts) else 1


async def _datasets_sync() -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        async with (
            RagflowClient.from_settings(settings) as client,
            session_factory(engine)() as session,
            session.begin(),
        ):
            results = await sync_datasets(
                session, client, tags, settings.models.ragflow.embedding_model
            )
            # P2A-01: documents whose RAGFlow status disagrees with the register.
            mismatches = await status_mismatches(session, client)
    finally:
        await engine.dispose()
    for result in results:
        log(
            "datasets.sync",
            level="error" if result.failed else "info",
            tag=result.tag,
            status=result.status,
            dataset_id=result.dataset_id,
        )
    for mismatch in mismatches:
        log(
            "datasets.status_mismatch",
            level="error",
            source_id=str(mismatch.source_id),
            tag=mismatch.tag,
            dataset_id=mismatch.dataset_id,
            status=f"expected_{mismatch.expected}_found_{mismatch.found}",
        )
    return 1 if mismatches or any(result.failed for result in results) else 0


@dataclass(frozen=True)
class _Actors:
    """Who proposes and who approves in this run (internal users), from the flags."""

    proposer_id: UUID | None
    reviewer_id: UUID | None


async def _actors(
    factory: async_sessionmaker[AsyncSession], propose_as: str | None, approve_as: str | None
) -> _Actors:
    """``--propose-as`` defaults to ``--approve-as``: whoever approves a run of our own
    corpus also proposed it (self-approval, audited). Roles are checked when used."""
    reviewer_id = await user_by_email(factory, approve_as) if approve_as else None
    proposer_id = await user_by_email(factory, propose_as) if propose_as else reviewer_id
    return _Actors(proposer_id, reviewer_id)


def _log_ingest(result: IngestResult) -> None:
    log(
        "ingest.result",
        level="error" if result.status == "failed" else "info",
        source_id=str(result.source_id),
        status=result.status,
        chunk_count=result.chunk_count,
        error_code=result.error_code,
    )


async def _load(location: str) -> SourceFile:
    if location.startswith(("http://", "https://")):
        async with http_client() as http:
            try:
                return from_fetched(await fetch(http, location))
            except FetchError as exc:
                # The code only: a FetchError's message names the URL (P1c-04).
                raise IngestError(exc.code, f"could not fetch the URL: {exc.code}") from None
    return load_path(Path(location))


async def _wait(
    factory: async_sessionmaker[AsyncSession], results: Sequence[IngestResult], wait: bool
) -> list[IngestResult]:
    """With ``--wait``, the results once the worker has run their jobs."""
    if not wait or not any(r.status == "queued" for r in results):
        return list(results)
    log("jobs.waiting", status="waiting", count=sum(r.status == "queued" for r in results))
    return await settle(factory, results)


async def _ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    is_url = args.location.startswith(("http://", "https://"))
    metadata = SourceMetadata(
        tags=tuple(args.tag),
        title=args.title,
        publisher=args.publisher,
        licence_basis=args.licence,
        published_on=args.published_on,
        canonical_url=args.canonical_url or (args.location if is_url else None),
        downloadable=args.downloadable,
    )
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        factory = session_factory(engine)
        actors = await _actors(factory, args.propose_as, args.approve_as)
        source = await _load(args.location)
        result = await submit(
            factory,
            tags,
            source,
            metadata,
            content_root=settings.models.files.content_root,
            proposer_id=actors.proposer_id,
            reviewer_id=actors.reviewer_id,
            parse_timeout=args.parse_timeout,
        )
        [result] = await _wait(factory, [result], args.wait)
    except IngestError as exc:
        # Usage problem; nothing recorded. The message names a file, URL or tag only.
        log("ingest.rejected", level="error", status="rejected", error_code=exc.code)
        raise SystemExit(f"ask-spore ingest: {exc}") from None
    except (RoleError, RegisterError) as exc:
        log("ingest.rejected", level="error", status="rejected", error_code=exc.code)
        raise SystemExit(f"ask-spore ingest: {exc.code}") from None
    finally:
        await engine.dispose()
    _log_ingest(result)
    return 1 if result.status == "failed" else 0


async def _crawl_site(
    tags: Mapping[str, TagConfig],
    factory: async_sessionmaker[AsyncSession],
    *,
    spec: SiteSpec,
    actors: _Actors,
    wait: bool,
) -> tuple[str, list[IngestResult]]:
    """Register a site and, with a reviewer, approve it (or ask for a crawl now); the
    worker crawls it (P1b-04). Returns the site's status (``proposed``, ``queued``,
    ``ok``, or an error code) and, after ``--wait``, the page ingestions the crawl
    queued, still to be settled. Raises RegisterError, RoleError or FetchError."""
    submission = await submit_site(
        factory,
        tags,
        spec,
        proposer_id=actors.proposer_id,
        reviewer_id=actors.reviewer_id,
    )
    log("crawl.submitted", status=submission.status, error_code=submission.error_code)
    if submission.status == "failed":
        return submission.error_code or "failed", []
    if not wait or submission.status != "queued":
        return submission.status, []
    log("jobs.waiting", status="waiting", count=1)
    status, results = await settle_site(factory, submission)
    log(
        "crawl.finished",
        level="info" if status == "ok" else "error",
        status=status,
        count=len(results),
    )
    return status, results


async def _crawl(args: argparse.Namespace) -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    unknown = [tag for tag in args.tag if tag not in tags]
    if unknown:
        raise SystemExit(f"ask-spore crawl: tags not in config/tags.toml: {', '.join(unknown)}")
    host = urlsplit(args.site_url).hostname or args.site_url
    spec = SiteSpec(
        start_url=args.site_url,
        name=args.name or host,
        publisher=args.publisher or host,
        licence_basis=args.licence,
        tags=tuple(args.tag),
        allow_patterns=tuple(args.allow or ()),
        deny_patterns=tuple(args.deny or ()),
        schedule=args.schedule,
        max_pages=args.max_pages,
    )
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        factory = session_factory(engine)
        actors = await _actors(factory, args.propose_as, args.approve_as)
        status, results = await _crawl_site(tags, factory, spec=spec, actors=actors, wait=args.wait)
        results = await _wait(factory, results, args.wait)
        for result in results:
            _log_ingest(result)
    except FetchError as exc:
        log("crawl.rejected", level="error", status="rejected", error_code=exc.code)
        raise SystemExit(f"ask-spore crawl: {exc.code}") from None
    except (RoleError, RegisterError) as exc:
        log("crawl.rejected", level="error", status="rejected", error_code=exc.code)
        raise SystemExit(f"ask-spore crawl: {exc.code}") from None
    finally:
        await engine.dispose()
    waiting = ("ok", "proposed", "queued")
    return 1 if status not in waiting or any(r.status == "failed" for r in results) else 0


def _log_outcomes(outcomes: Sequence[RowOutcome]) -> None:
    """The summary table: one metadata-only line per manifest row, then totals per status."""
    for o in outcomes:
        log(
            "manifest.row",
            level="error" if o.status == "failed" else "info",
            manifest_line=o.line,
            status=o.status,
            chunk_count=o.chunk_count,
            count=len(o.source_ids),
            latency_ms=round(o.seconds * 1000),
            source_id=str(o.source_ids[0]) if len(o.source_ids) == 1 else None,
            error_code=o.error_code,
        )
    for status in sorted({o.status for o in outcomes}):
        rows = [o for o in outcomes if o.status == status]
        log(
            "manifest.summary",
            status=status,
            count=len(rows),
            chunk_count=sum(o.chunk_count for o in rows),
            latency_ms=round(sum(o.seconds for o in rows) * 1000),
        )


async def _ingest_manifest(args: argparse.Namespace) -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    try:
        rows = load_manifest(Path(args.manifest), tags)
    except ManifestError as exc:
        log("manifest.invalid", level="error", status="invalid", count=len(exc.problems))
        raise SystemExit(f"ask-spore ingest-manifest: {exc}") from None
    log("manifest.valid", status="ok", count=len(rows))
    if args.check:
        return 0

    engine = create_engine(settings.secrets.database_url.get_secret_value())
    factory = session_factory(engine)
    content_root = settings.models.files.content_root
    submitted: dict[int, tuple[float, str | None, list[IngestResult]]] = {}
    try:
        try:
            actors = await _actors(factory, args.propose_as, args.approve_as)
        except RoleError as exc:
            log("manifest.rejected", level="error", status="rejected", error_code=exc.code)
            raise SystemExit(f"ask-spore ingest-manifest: {exc.code}") from None

        async def ingest_file(row: ManifestRow) -> IngestResult:
            if row.path is None:
                raise AssertionError("validated file rows have a path")
            try:
                result = await submit(
                    factory,
                    tags,
                    load_path(row.path),
                    row.metadata,
                    content_root=content_root,
                    proposer_id=actors.proposer_id,
                    reviewer_id=actors.reviewer_id,
                    parse_timeout=args.parse_timeout,
                )
            except IngestError as exc:  # validated, so only no_dataset or I/O
                raise SystemExit(f"ask-spore ingest-manifest: line {row.line}: {exc}") from None
            except (RoleError, RegisterError) as exc:
                raise SystemExit(
                    f"ask-spore ingest-manifest: line {row.line}: {exc.code}"
                ) from None
            _log_ingest(result)
            submitted[row.line] = (0.0, None, [result])
            return result

        async def crawl_site(row: ManifestRow) -> tuple[str, list[IngestResult]]:
            if row.url is None:
                raise AssertionError("validated site rows have a URL")
            spec = SiteSpec(
                start_url=row.url,
                name=row.metadata.title,
                publisher=row.metadata.publisher,
                licence_basis=row.metadata.licence_basis,
                tags=row.metadata.tags,
                max_pages=row.max_pages,
            )
            try:
                status, results = await _crawl_site(
                    tags, factory, spec=spec, actors=actors, wait=args.wait
                )
            except FetchError as exc:
                log("crawl.failed", level="error", status="failed", error_code=exc.code)
                status, results = exc.code, []
            except (RoleError, RegisterError) as exc:
                raise SystemExit(
                    f"ask-spore ingest-manifest: line {row.line}: {exc.code}"
                ) from None
            submitted[row.line] = (0.0, status, results)
            return status, results

        outcomes = await run_manifest(rows, ingest_file, crawl_site)
        if args.wait:
            flat = [r for _, _, results in submitted.values() for r in results]
            settled = iter(await _wait(factory, flat, args.wait))
            by_line = {
                line: [next(settled) for _ in results]
                for line, (_, _, results) in submitted.items()
            }
            outcomes = [
                row_outcome(row, by_line[row.line], outcome.seconds, submitted[row.line][1])
                for row, outcome in zip(rows, outcomes, strict=True)
            ]
            for result in (r for results in by_line.values() for r in results):
                _log_ingest(result)
    finally:
        await engine.dispose()
    _log_outcomes(outcomes)
    if args.summary:
        write_summary(outcomes, Path(args.summary))
    return 1 if any(o.status == "failed" for o in outcomes) else 0


async def _content_roles(args: argparse.Namespace) -> int:
    """Grant or revoke a content role, as the owner (MIGRATIONS_DATABASE_URL)."""
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL", "").strip()
    if not owner_url:
        log("content_roles.failed", level="error", error_code="no_owner_database_url")
        return 1
    engine = create_engine(owner_url)
    try:
        factory = session_factory(engine)
        if args.content_roles_command == "grant":
            result: str = await grant_role(factory, email=args.email, role=args.role)
        else:
            result = await revoke_role(factory, email=args.email, role=args.role)
    finally:
        await engine.dispose()
    failed = result in ("no_user", "not_granted")
    log(
        "content_roles." + args.content_roles_command,
        level="error" if failed else "info",
        status=result,
    )
    return 1 if failed else 0


async def _sources(args: argparse.Namespace) -> int:
    """A reviewer's decision on one register row: approve or retry (each queues an
    ingestion job), reject, withdraw (queues the withdrawal job) or record a takedown."""
    settings = get_settings()
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    source_id: UUID = args.source_id
    try:
        factory = session_factory(engine)
        reviewer_id = await user_by_email(factory, args.reviewer)
        if args.sources_command == "reject":
            await reject(factory, source_id, reviewer_id, note=args.note)
            log("sources.reject", source_id=str(source_id), status="rejected")
            return 0
        if args.sources_command == "takedown":
            await record_takedown(
                factory,
                source_id,
                reviewer_id,
                reference=args.reference,
                requested_on=args.requested_on,
                licence_breach=args.licence_breach,
                licence_grounds=args.licence_grounds,
            )
            log("sources.takedown", source_id=str(source_id), status="recorded")
            return 0
        if args.sources_command == "restore":
            site_id = await restore_page(factory, source_id, reviewer_id)
            log("sources.restore", source_id=str(source_id), site_id=str(site_id), status="ok")
            return 0
        if args.sources_command == "withdraw":
            job_id = await request_withdrawal(factory, source_id, reviewer_id, reason=args.reason)
            if args.wait:
                found = await wait_for(factory, [job_id])
                state = found[job_id]
                log(
                    "sources.withdraw",
                    level="info" if state.status == "succeeded" else "error",
                    source_id=str(source_id),
                    job_id=str(job_id),
                    status=state.status,
                    error_code=state.error_code,
                )
                return 0 if state.status == "succeeded" else 1
            log("sources.withdraw", source_id=str(source_id), job_id=str(job_id), status="queued")
            return 0
        if args.sources_command == "approve":
            job_id = await approve(
                factory,
                source_id,
                reviewer_id,
                note=args.note,
                parse_timeout=args.parse_timeout,
                replaces=args.replace,
                keep_both=args.keep_both,
            )
        else:
            job_id = await retry(factory, source_id, reviewer_id, parse_timeout=args.parse_timeout)
        queued = IngestResult(source_id=source_id, status="queued", job_id=job_id)
        [result] = await _wait(factory, [queued], args.wait)
    except (RoleError, RegisterError) as exc:
        log(
            "sources." + args.sources_command,
            level="error",
            source_id=str(source_id),
            status="refused",
            error_code=exc.code,
        )
        return 1
    finally:
        await engine.dispose()
    _log_ingest(result)
    return 1 if result.status == "failed" else 0


async def _sites(args: argparse.Namespace) -> int:
    """A reviewer withdraws a whole site (P1c-14): retired, never crawled again, every
    page withdrawn by its own ``withdraw_source`` job."""
    settings = get_settings()
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    site_id: UUID = args.site_id
    try:
        factory = session_factory(engine)
        reviewer_id = await user_by_email(factory, args.reviewer)
        job_ids = await withdraw_site(factory, site_id, reviewer_id, reason=args.reason)
        status = "queued"
        if args.wait and job_ids:
            found = await wait_for(factory, job_ids)
            failed = [j for j, state in found.items() if state.status != "succeeded"]
            status = "failed" if failed else "succeeded"
    except (RoleError, RegisterError) as exc:
        log(
            "sites.withdraw",
            level="error",
            site_id=str(site_id),
            status="refused",
            error_code=exc.code,
        )
        return 1
    finally:
        await engine.dispose()
    log(
        "sites.withdraw",
        level="error" if status == "failed" else "info",
        site_id=str(site_id),
        count=len(job_ids),
        status=status,
    )
    return 1 if status == "failed" else 0


async def _tick(factory: async_sessionmaker[AsyncSession], notices: ConsentNoticeTick) -> None:
    """Between jobs: due crawls (P1b-04), the daily purge (P1b-14), consent notices (P1b-10)."""
    await schedule_due_crawls(factory)
    await schedule_purge(factory)
    await notices()


async def _purge(args: argparse.Namespace) -> int:
    """The retention purge (P1b-14): count what is due, or queue the job for the worker."""
    settings = get_settings()
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    factory = session_factory(engine)
    try:
        if args.dry_run:
            due = await purge_retention(
                factory, downloads_days=settings.models.retention.downloads_days, dry_run=True
            )
            for tenant in due:
                for table, count in tenant.counts.as_dict().items():
                    if count:
                        log(
                            "retention.due",
                            tenant_id=str(tenant.tenant_id),
                            table=table,
                            count=count,
                        )
            log("retention.dry_run", status="dry_run", count=sum(t.counts.total for t in due))
            return 0
        async with factory() as session, session.begin():
            job_id = await enqueue(session, "purge_retention", {}, created_by=None, max_attempts=1)
        log("retention.queued", job_id=str(job_id), job_type="purge_retention", status="queued")
        if not args.wait:
            return 0
        state = (await wait_for(factory, [job_id]))[job_id]
        log(
            "retention.job",
            level="info" if state.status == "succeeded" else "error",
            job_id=str(job_id),
            status=state.status,
            error_code=state.error_code,
        )
        return 0 if state.status == "succeeded" else 1
    finally:
        await engine.dispose()


async def _tenant_purge(args: argparse.Namespace) -> int:
    """Termination purge of one tenant (P1b-14), as the schema owner (MIGRATIONS_DATABASE_URL)."""
    settings = get_settings()
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL", "").strip()
    if not owner_url:
        log("tenant.purge_failed", level="error", error_code="no_owner_database_url")
        return 1
    cache.connect(settings.secrets.redis_url.get_secret_value())
    engine = create_engine(owner_url)
    try:
        done = await terminate_tenant(
            session_factory(engine),
            slug=args.slug,
            confirm=args.confirm,
            content_root=settings.models.files.content_root,
        )
    except TerminationError as exc:
        log("tenant.purge_failed", level="error", error_code=exc.code)
        return 1
    finally:
        await cache.close()
        await engine.dispose()
    for table, count in done.counts.items():
        log("tenant.purged_rows", tenant_id=str(done.tenant_id), table=table, count=count)
    # The certificate's number names its file under content_root/certificates/.
    log(
        "tenant.purged",
        tenant_id=str(done.tenant_id),
        status="purged",
        count=done.total,
        certificate=done.certificate_number,
    )
    return 0


async def _worker(args: argparse.Namespace) -> int:
    """Run the job queue until stopped (SIGTERM or SIGINT puts the running job back)."""
    settings = get_settings()
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    task = asyncio.current_task()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal() -> None:
        stop.set()
        if task is not None:
            task.cancel()

    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not on every platform
            loop.add_signal_handler(signum, on_signal)
    # The withdrawal job purges answer caches (P1b-03), only through app.core.cache.
    cache.connect(settings.secrets.redis_url.get_secret_value())
    # P1b-11: platform mail, through the configured provider (None without its key).
    sender = create_mail_sender(settings)
    if settings.models.mail is not None and sender is None:
        log("worker.mail_not_configured", level="warning", status="no_sender")
    factory = session_factory(engine)
    # P1b-10: one consent-notice email per user when the notice version changes.
    notices = ConsentNoticeTick(factory, settings.models.consent.version)
    try:
        async with RagflowClient.from_settings(settings) as client:
            context = worker.Context(
                factory=factory,
                client=client,
                tags=load_tags(settings.config_dir),
                content_root=settings.models.files.content_root,
                downloads_retention_days=settings.models.retention.downloads_days,
                mail=MailContext(
                    factory=factory,
                    config=settings.models.mail,
                    config_dir=settings.config_dir,
                    sender=sender,
                ),
            )
            await worker.run(
                context.factory,
                worker.handlers(context),
                poll_interval=args.poll_interval,
                stop=stop,
                once=args.once,
                tick=lambda: _tick(context.factory, notices),
            )
    except asyncio.CancelledError:
        log("worker.stopped", status="stopped")
    finally:
        if sender is not None:
            await sender.aclose()
        await cache.close()
        await engine.dispose()
    return 0


async def _eval_identity(args: argparse.Namespace) -> int:
    """Create the eval harness's service identity (P1b-15 a), as the schema owner."""
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL", "").strip()
    if not owner_url:
        log("eval_identity.failed", level="error", error_code="no_owner_database_url")
        return 1
    engine = create_engine(owner_url)
    try:
        result = await create_eval_identity(session_factory(engine), email=args.email)
    finally:
        await engine.dispose()
    failed = result == "has_roles"
    log("eval_identity.create", level="error" if failed else "info", status=result)
    return 1 if failed else 0


async def _operators(args: argparse.Namespace) -> int:
    """Grant or revoke the operator role, as the owner (MIGRATIONS_DATABASE_URL)."""
    settings = get_settings()
    owner_url = os.environ.get("MIGRATIONS_DATABASE_URL", "").strip()
    if not owner_url:
        log("operators.failed", level="error", error_code="no_owner_database_url")
        return 1
    engine = create_engine(owner_url)
    try:
        factory = session_factory(engine)
        if args.operators_command == "revoke":
            result: str = await revoke_operator(factory, email=args.email)
        elif settings.models.auth.mode == "oidc":
            async with httpx.AsyncClient(timeout=10) as http:
                _, provider = oidc_services(settings, http)
                try:
                    result = await grant_operator(
                        factory, email=args.email, display_name=args.name, provider=provider
                    )
                finally:
                    await provider.aclose()
        else:
            result = await grant_operator(
                factory, email=args.email, display_name=args.name, provider=None
            )
    except ProviderError as exc:
        log("operators.failed", level="error", error_code=exc.error_code)
        return 1
    finally:
        await engine.dispose()
    failed = result in ("no_user", "not_operator")
    log("operators." + args.operators_command, level="error" if failed else "info", status=result)
    return 1 if failed else 0


def _wait_flag(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--wait",
        action="store_true",
        help="wait for the worker to run the queued jobs and report what they did",
    )


def _actor_flags(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--approve-as",
        metavar="EMAIL",
        help="a content reviewer (internal user) who approves the proposals in this run, "
        "audited; without it they wait for a reviewer",
    )
    command.add_argument(
        "--propose-as",
        metavar="EMAIL",
        help="the content editor proposing (default: the --approve-as user)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-spore", description="ask.spore content operations (Phase 0)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    datasets = commands.add_parser("datasets", help="RAGFlow datasets, one per tag")
    datasets_commands = datasets.add_subparsers(dest="datasets_command", required=True)
    datasets_commands.add_parser(
        "sync", help="create missing datasets for config/tags.toml and record the mapping"
    )
    datasets_commands.add_parser(
        "counts",
        help="RAGFlow's document and chunk counts per mapped tag (P1c-10; metadata only)",
    )

    ingest_cmd = commands.add_parser(
        "ingest",
        help="register one source and ingest it into the datasets of its tags",
        description="Supported: PDF, DOCX, PPTX, HTML and Markdown files, or an http(s) URL "
        "serving one of them. The source's error, if any, is recorded on its sources row.",
    )
    ingest_cmd.add_argument("location", help="file path or http(s) URL")
    ingest_cmd.add_argument(
        "--tag", action="append", required=True, help="content tag; repeat for several"
    )
    ingest_cmd.add_argument("--title", required=True)
    ingest_cmd.add_argument("--publisher", required=True)
    ingest_cmd.add_argument(
        "--licence",
        required=True,
        help='licence basis: licence name, permission letter reference, or "own work"',
    )
    ingest_cmd.add_argument(
        "--published-on", type=date.fromisoformat, help="publication date, YYYY-MM-DD"
    )
    ingest_cmd.add_argument(
        "--canonical-url", help="link shown to users (defaults to the URL when ingesting one)"
    )
    ingest_cmd.add_argument(
        "--parse-timeout",
        type=float,
        default=1800.0,
        help="seconds to wait for RAGFlow to finish parsing (default 1800)",
    )
    ingest_cmd.add_argument(
        "--downloadable",
        action="store_true",
        help="users may download the file (PDF, DOCX, PPTX); only where the licence permits",
    )
    _actor_flags(ingest_cmd)
    _wait_flag(ingest_cmd)

    crawl_cmd = commands.add_parser(
        "crawl",
        help="register a site for crawling (P1b-04); with --approve-as, approve and crawl it",
        description="Registers the site in the sites table (the content console's Sites "
        "page shows it). The worker crawls an approved site: robots.txt, crawl delay and "
        "the text-and-data-mining reservation are honoured, special-category pages are "
        "skipped, and each page becomes a register row. Same host only.",
    )
    crawl_cmd.add_argument("site_url", help="start URL; only pages on its host are crawled")
    crawl_cmd.add_argument("--tag", action="append", required=True, help="content tag")
    crawl_cmd.add_argument("--max-pages", type=int, required=True, help="page budget")
    crawl_cmd.add_argument("--licence", required=True, help="licence basis for the site")
    crawl_cmd.add_argument("--publisher", help="publisher name (defaults to the host name)")
    crawl_cmd.add_argument("--name", help="the site's name (defaults to the host name)")
    crawl_cmd.add_argument(
        "--allow", action="append", metavar="PATTERN", help="path pattern to crawl, e.g. /reports/*"
    )
    crawl_cmd.add_argument(
        "--deny", action="append", metavar="PATTERN", help="path pattern never to crawl"
    )
    crawl_cmd.add_argument(
        "--schedule", choices=("none", "weekly", "monthly"), default="none", help="re-crawl"
    )
    _actor_flags(crawl_cmd)
    _wait_flag(crawl_cmd)

    manifest_cmd = commands.add_parser(
        "ingest-manifest",
        help="ingest every row of a corpus manifest.csv (design/specs/corpus-manifest.md)",
        description="Validates every row against config/tags.toml and the file tree first and "
        "uploads nothing if any row is invalid. Files already ingested (same content hash) are "
        "reported as duplicate, so re-running after a failure is safe; a row that gives such "
        "a file a tag it lacks links it into that tag's dataset and is reported as retagged. "
        "PDF, DOCX and PPTX files are also stored under [files] content_root for downloads; "
        "the optional downloadable column (default false) sets the licence gate of new and "
        "retagged sources.",
    )
    manifest_cmd.add_argument(
        "manifest", help="path to manifest.csv; file paths are relative to it"
    )
    manifest_cmd.add_argument("--check", action="store_true", help="validate only; upload nothing")
    manifest_cmd.add_argument(
        "--summary", help="also write the summary table to this CSV file (no titles or content)"
    )
    manifest_cmd.add_argument("--parse-timeout", type=float, default=1800.0)
    _actor_flags(manifest_cmd)
    _wait_flag(manifest_cmd)

    roles = commands.add_parser(
        "content-roles",
        help="grant or revoke a content role (P1b-01)",
        description="Runs as the schema owner (MIGRATIONS_DATABASE_URL). content_editor "
        "proposes sources; content_reviewer approves, rejects, retries and withdraws them. "
        "The user must exist in the internal tenant.",
    )
    roles_commands = roles.add_subparsers(dest="content_roles_command", required=True)
    for name in ("grant", "revoke"):
        role_cmd = roles_commands.add_parser(name, help=f"{name} a content role")
        role_cmd.add_argument("--email", required=True)
        role_cmd.add_argument(
            "--role", required=True, choices=["content_editor", "content_reviewer"]
        )

    sources = commands.add_parser(
        "sources", help="a reviewer's decision on one source register row (P1b-01)"
    )
    sources_commands = sources.add_subparsers(dest="sources_command", required=True)
    for name, text in (
        ("approve", "approve a proposed source and ingest it"),
        ("reject", "reject a proposed source, with a note"),
        ("retry", "send a failed source back for ingestion"),
    ):
        source_cmd = sources_commands.add_parser(name, help=text)
        source_cmd.add_argument("source_id", type=UUID)
        source_cmd.add_argument("--as", dest="reviewer", required=True, metavar="EMAIL")
        if name != "retry":
            source_cmd.add_argument("--note", required=name == "reject")
        if name != "reject":
            source_cmd.add_argument("--parse-timeout", type=float, default=1800.0)
            _wait_flag(source_cmd)
        if name == "approve":
            # Owner decisions 4 (Oct 22) and 3 (Oct 23, 2026): a proposal at the canonical
            # link of an ingested source under another title needs the reviewer's choice;
            # with the same title it replaces that source unless --keep-both is given.
            choice = source_cmd.add_mutually_exclusive_group()
            choice.add_argument(
                "--replace",
                type=UUID,
                metavar="SOURCE_ID",
                help="the ingested source at the same canonical link that this file replaces",
            )
            choice.add_argument(
                "--keep-both",
                action="store_true",
                help="keep the ingested source at the same canonical link beside this one",
            )

    withdraw_cmd = sources_commands.add_parser(
        "withdraw",
        help="withdraw a source everywhere: every dataset, the answer caches, and stored "
        "citations flagged (P1b-03)",
    )
    withdraw_cmd.add_argument("source_id", type=UUID)
    withdraw_cmd.add_argument("--as", dest="reviewer", required=True, metavar="EMAIL")
    withdraw_cmd.add_argument("--reason", required=True, help="kept on the register row")
    _wait_flag(withdraw_cmd)

    restore_cmd = sources_commands.add_parser(
        "restore",
        help="restore a crawled page a reviewer withdrew: the next crawl of its site takes "
        "it again (P1c-14)",
    )
    restore_cmd.add_argument("source_id", type=UUID, help="the page's withdrawn register row")
    restore_cmd.add_argument("--as", dest="reviewer", required=True, metavar="EMAIL")

    sites_parser = commands.add_parser(
        "sites", help="a reviewer's decision on a registered site (P1c-14)"
    )
    sites_commands = sites_parser.add_subparsers(dest="sites_command", required=True)
    site_withdraw = sites_commands.add_parser(
        "withdraw",
        help="withdraw a whole site: retired (no further crawls), every page withdrawn from "
        "every dataset, the answer caches and stored citations",
    )
    site_withdraw.add_argument("site_id", type=UUID)
    site_withdraw.add_argument("--as", dest="reviewer", required=True, metavar="EMAIL")
    site_withdraw.add_argument("--reason", required=True, help="kept on the site and its rows")
    _wait_flag(site_withdraw)

    takedown_cmd = sources_commands.add_parser(
        "takedown",
        help="put a source on the takedown queue: due 10 working days after the request, "
        "or at once for a licence breach we find ourselves",
    )
    takedown_cmd.add_argument("source_id", type=UUID)
    takedown_cmd.add_argument("--as", dest="reviewer", required=True, metavar="EMAIL")
    takedown_cmd.add_argument("--reference", required=True, help="the request's reference")
    takedown_cmd.add_argument(
        "--requested-on", type=date.fromisoformat, required=True, help="YYYY-MM-DD"
    )
    takedown_cmd.add_argument(
        "--licence-breach", action="store_true", help="a breach we found ourselves: due today"
    )
    takedown_cmd.add_argument(
        "--licence-grounds",
        action="store_true",
        help="the request is on licence grounds, recorded on the queue (implied by "
        "--licence-breach); every withdrawal blanks stored excerpts",
    )

    worker_cmd = commands.add_parser(
        "worker",
        help="run the background job queue (P1b-02): ingestion of approved sources",
        description="Polls the jobs table and runs one job at a time. Runs as the worker "
        "Compose service, with the API's configuration and secrets.",
    )
    worker_cmd.add_argument(
        "--once", action="store_true", help="run until the queue is empty, then exit"
    )
    worker_cmd.add_argument(
        "--poll-interval", type=float, default=5.0, help="seconds between polls when idle"
    )

    purge_cmd = commands.add_parser(
        "purge",
        help="the retention purge (P1b-14): expired history, revoked sessions, old downloads",
        description="Deletes, tenant by tenant under row-level security, conversations past "
        "their expiry (with messages, citations and feedback), revoked_sessions rows past "
        "their token's expiry and downloads rows older than [retention] downloads_days. The "
        "worker runs it once a day; --run queues it now. Output is counts only.",
    )
    purge_mode = purge_cmd.add_mutually_exclusive_group(required=True)
    purge_mode.add_argument(
        "--dry-run", action="store_true", help="count what is due per tenant; delete nothing"
    )
    purge_mode.add_argument(
        "--run", action="store_true", help="queue a purge_retention job for the worker"
    )
    _wait_flag(purge_cmd)

    tenant_cmd = commands.add_parser(
        "tenant", help="tenant lifecycle, operator only (P1b-14: termination purge)"
    )
    tenant_commands = tenant_cmd.add_subparsers(dest="tenant_command", required=True)
    tenant_purge = tenant_commands.add_parser(
        "purge",
        help="terminate a tenant: delete its history, account data, workspaces, prompts, "
        "settings, downloads and sessions, clear its answer cache, write the certificate",
        description="Runs as the schema owner (MIGRATIONS_DATABASE_URL), in one transaction, "
        "audited under the internal tenant (tenant.purged). Keeps the audit events and the "
        "usage ledger. Writes certificates/<number>.json under [files] content_root. The "
        "tenant's Authentik users and SSO source are removed by hand afterwards (see "
        "design/compliance/offboarding-pack.md section 1.4). Cannot be undone.",
    )
    tenant_purge.add_argument("--slug", required=True, help="the tenant to terminate")
    tenant_purge.add_argument(
        "--confirm", required=True, metavar="SLUG", help="the same slug again, to confirm"
    )

    eval_cmd = commands.add_parser(
        "eval-identity",
        help="the eval harness's service identity under oidc (P1b-15 a)",
        description="Runs as the schema owner (MIGRATIONS_DATABASE_URL). Creates a plain "
        "active user of the internal tenant (role user, no operator or content role, not "
        "in Authentik) for the eval harness's signed credential; an API accepts it only "
        "with [auth.eval_service] set to that email and the harness's public key "
        "(packages/eval/README.md).",
    )
    eval_commands = eval_cmd.add_subparsers(dest="eval_identity_command", required=True)
    eval_create = eval_commands.add_parser("create", help="create the service identity")
    eval_create.add_argument("--email", required=True)

    operators = commands.add_parser(
        "operators",
        help="grant or revoke the platform operator role (P1a-03)",
        description="Runs as the schema owner (MIGRATIONS_DATABASE_URL). An operator is a "
        "user of the internal tenant; grant creates that user when --name is given.",
    )
    operators_commands = operators.add_subparsers(dest="operators_command", required=True)
    grant_cmd = operators_commands.add_parser("grant", help="make an internal user an operator")
    grant_cmd.add_argument("--email", required=True)
    grant_cmd.add_argument("--name", help="display name; creates the internal user if missing")
    revoke_cmd = operators_commands.add_parser("revoke", help="remove the operator role")
    revoke_cmd.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "datasets" and args.datasets_command == "sync":
        return asyncio.run(_datasets_sync())
    if args.command == "datasets" and args.datasets_command == "counts":
        return asyncio.run(_datasets_counts())
    if args.command == "ingest":
        return asyncio.run(_ingest(args))
    if args.command == "crawl":
        if args.max_pages < 1:
            raise SystemExit("ask-spore crawl: --max-pages must be at least 1")
        return asyncio.run(_crawl(args))
    if args.command == "ingest-manifest":
        return asyncio.run(_ingest_manifest(args))
    if args.command == "operators":
        return asyncio.run(_operators(args))
    if args.command == "content-roles":
        return asyncio.run(_content_roles(args))
    if args.command == "sources":
        return asyncio.run(_sources(args))
    if args.command == "sites":
        return asyncio.run(_sites(args))
    if args.command == "worker":
        return asyncio.run(_worker(args))
    if args.command == "purge":
        return asyncio.run(_purge(args))
    if args.command == "eval-identity":
        return asyncio.run(_eval_identity(args))
    if args.command == "tenant":
        return asyncio.run(_tenant_purge(args))
    raise AssertionError("unreachable: argparse enforces the commands")


if __name__ == "__main__":
    raise SystemExit(main())
