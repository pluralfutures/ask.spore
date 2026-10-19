"""``ask-spore`` command line for content operations (P0-08 to P0-11) and for granting
the operator role (P1a-03, ``operators grant|revoke``, as the schema owner).

Runs where the API runs (inside the Compose network, e.g.
``docker compose -f infra/compose.dev.yml run --rm api ask-spore datasets sync``):
it needs the same configuration and secrets, and reaches RAGFlow on the internal
network. Output is metadata-only JSON log lines via app.core.logging.log();
the exit status is non-zero when anything failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.authentik import oidc_services
from app.auth.provider import ProviderError
from app.content.crawler import crawl, page_markdown, write_pages
from app.content.datasets import sync_datasets
from app.content.fetch import FetchError, fetch, http_client
from app.content.ingest import (
    IngestError,
    IngestResult,
    SourceFile,
    SourceMetadata,
    from_fetched,
    ingest,
    load_path,
)
from app.content.manifest import (
    ManifestError,
    ManifestRow,
    RowOutcome,
    load_manifest,
    run_manifest,
    write_summary,
)
from app.content.tags import TagConfig, load_tags
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
    )
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        source = await _load(args.location)
        async with RagflowClient.from_settings(settings) as client:
            result = await ingest(
                session_factory(engine),
                client,
                tags,
                source,
                metadata,
                parse_timeout=args.parse_timeout,
            )
    except IngestError as exc:
        # Usage problem; nothing recorded. The message names a file, URL or tag only.
        log("ingest.rejected", level="error", status="rejected", error_code=exc.code)
        raise SystemExit(f"ask-spore ingest: {exc}") from None
    finally:
        await engine.dispose()
    _log_ingest(result)
    return 1 if result.status == "failed" else 0


async def _crawl_site(
    tags: Mapping[str, TagConfig],
    client: RagflowClient,
    factory: async_sessionmaker[AsyncSession],
    *,
    site_url: str,
    tag: Sequence[str],
    max_pages: int,
    licence: str,
    publisher: str | None,
    out_dir: str | None,
    parse_timeout: float,
) -> tuple[str, list[IngestResult]]:
    """Crawl one site and ingest every page; returns the crawl status and the results.

    Raises FetchError when the start URL cannot be fetched at all.
    """
    async with http_client() as http:
        report = await crawl(http, site_url, max_pages)
    for reason, count in sorted(report.skipped.items()):
        log("crawl.skipped", status=reason, chunk_count=count)
    log(
        "crawl.finished",
        level="info" if report.status == "ok" else "error",
        status=report.status,
        chunk_count=len(report.pages),
    )
    if report.status != "ok":
        return report.status, []

    paths = write_pages(report.pages, Path(out_dir or tempfile.mkdtemp(prefix="ask-spore-crawl-")))
    publisher = publisher or (urlsplit(site_url).hostname or site_url)
    results: list[IngestResult] = []
    for page, path in zip(report.pages, paths, strict=True):
        result = await ingest(
            factory,
            client,
            tags,
            SourceFile(path.name, "markdown", page_markdown(page).encode()),
            SourceMetadata(
                tags=tuple(tag),
                title=page.title,
                publisher=publisher,
                licence_basis=licence,
                canonical_url=page.url,
            ),
            parse_timeout=parse_timeout,
        )
        _log_ingest(result)
        results.append(result)
    return "ok", results


async def _crawl(args: argparse.Namespace) -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    unknown = [tag for tag in args.tag if tag not in tags]
    if unknown:
        raise SystemExit(f"ask-spore crawl: tags not in config/tags.toml: {', '.join(unknown)}")
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    try:
        async with RagflowClient.from_settings(settings) as client:
            status, results = await _crawl_site(
                tags,
                client,
                session_factory(engine),
                site_url=args.site_url,
                tag=args.tag,
                max_pages=args.max_pages,
                licence=args.licence,
                publisher=args.publisher,
                out_dir=args.out_dir,
                parse_timeout=args.parse_timeout,
            )
    except FetchError as exc:
        raise SystemExit(f"ask-spore crawl: {exc}") from None
    finally:
        await engine.dispose()
    return 1 if status != "ok" or any(r.status == "failed" for r in results) else 0


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
    try:
        async with RagflowClient.from_settings(settings) as client:

            async def ingest_file(row: ManifestRow) -> IngestResult:
                if row.path is None:
                    raise AssertionError("validated file rows have a path")
                try:
                    result = await ingest(
                        factory,
                        client,
                        tags,
                        load_path(row.path),
                        row.metadata,
                        parse_timeout=args.parse_timeout,
                    )
                except IngestError as exc:  # validated, so only no_dataset or I/O
                    raise SystemExit(f"ask-spore ingest-manifest: line {row.line}: {exc}") from None
                _log_ingest(result)
                return result

            async def crawl_site(row: ManifestRow) -> tuple[str, list[IngestResult]]:
                if row.url is None:
                    raise AssertionError("validated site rows have a URL")
                try:
                    return await _crawl_site(
                        tags,
                        client,
                        factory,
                        site_url=row.url,
                        tag=row.metadata.tags,
                        max_pages=row.max_pages,
                        licence=row.metadata.licence_basis,
                        publisher=row.metadata.publisher,
                        out_dir=str(Path(args.crawl_dir) / f"line-{row.line}")
                        if args.crawl_dir
                        else None,
                        parse_timeout=args.parse_timeout,
                    )
                except FetchError as exc:
                    log("crawl.failed", level="error", status="failed", error_code=exc.code)
                    return exc.code, []

            outcomes = await run_manifest(rows, ingest_file, crawl_site)
    finally:
        await engine.dispose()
    _log_outcomes(outcomes)
    if args.summary:
        write_summary(outcomes, Path(args.summary))
    return 1 if any(o.status == "failed" for o in outcomes) else 0


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

    crawl_cmd = commands.add_parser(
        "crawl",
        help="crawl one site and ingest each page as Markdown",
        description="Honours robots.txt and crawl delay; a text-and-data-mining reservation "
        "(TDMRep) anywhere on the site blocks the whole site. Same host only, no scheduling.",
    )
    crawl_cmd.add_argument("site_url", help="start URL; only pages on its host are crawled")
    crawl_cmd.add_argument("--tag", action="append", required=True, help="content tag")
    crawl_cmd.add_argument("--max-pages", type=int, required=True, help="page budget")
    crawl_cmd.add_argument("--licence", required=True, help="licence basis for the site")
    crawl_cmd.add_argument("--publisher", help="publisher name (defaults to the host name)")
    crawl_cmd.add_argument(
        "--out-dir", help="directory for the rendered Markdown files (default: a new temp dir)"
    )
    crawl_cmd.add_argument("--parse-timeout", type=float, default=1800.0)

    manifest_cmd = commands.add_parser(
        "ingest-manifest",
        help="ingest every row of a corpus manifest.csv (design/specs/corpus-manifest.md)",
        description="Validates every row against config/tags.toml and the file tree first and "
        "uploads nothing if any row is invalid. Files already ingested (same content hash) are "
        "reported as duplicate, so re-running after a failure is safe.",
    )
    manifest_cmd.add_argument(
        "manifest", help="path to manifest.csv; file paths are relative to it"
    )
    manifest_cmd.add_argument("--check", action="store_true", help="validate only; upload nothing")
    manifest_cmd.add_argument(
        "--summary", help="also write the summary table to this CSV file (no titles or content)"
    )
    manifest_cmd.add_argument(
        "--crawl-dir", help="directory for crawled Markdown, one sub-folder per site row"
    )
    manifest_cmd.add_argument("--parse-timeout", type=float, default=1800.0)

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
    raise AssertionError("unreachable: argparse enforces the commands")


if __name__ == "__main__":
    raise SystemExit(main())
