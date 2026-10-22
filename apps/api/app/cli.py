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
from app.content import worker
from app.content.datasets import sync_datasets
from app.content.fetch import FetchError, fetch, http_client
from app.content.ingest import (
    IngestError,
    IngestResult,
    SourceFile,
    SourceMetadata,
    from_fetched,
    load_path,
)
from app.content.jobs import wait_for
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
from app.content.sites import SiteSpec, schedule_due_crawls
from app.content.submit import settle, settle_site, submit, submit_site
from app.content.tags import TagConfig, load_tags
from app.core import cache
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
from app.operator.grants import grant_operator, revoke_operator
from app.retrieval.ragflow import RagflowClient


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
    return 1 if any(result.failed for result in results) else 0


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
                raise IngestError(exc.code, str(exc)) from None
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
    try:
        async with RagflowClient.from_settings(settings) as client:
            context = worker.Context(
                factory=session_factory(engine),
                client=client,
                tags=load_tags(settings.config_dir),
                content_root=settings.models.files.content_root,
            )
            await worker.run(
                context.factory,
                worker.handlers(context),
                poll_interval=args.poll_interval,
                stop=stop,
                once=args.once,
                tick=lambda: schedule_due_crawls(context.factory),
            )
    except asyncio.CancelledError:
        log("worker.stopped", status="stopped")
    finally:
        await cache.close()
        await engine.dispose()
    return 0


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
            # Owner decision 4 (Oct 22, 2026): a proposal at the canonical link of an
            # ingested source needs the reviewer's choice.
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
        help="the request is on licence grounds: the withdrawal blanks stored excerpts "
        "(implied by --licence-breach)",
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
    if args.command == "worker":
        return asyncio.run(_worker(args))
    raise AssertionError("unreachable: argparse enforces the commands")


if __name__ == "__main__":
    raise SystemExit(main())
