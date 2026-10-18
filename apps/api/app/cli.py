"""``ask-spore`` command line for content operations (P0-08 to P0-10).

Runs where the API runs (inside the Compose network, e.g.
``docker compose -f infra/compose.dev.yml run --rm api ask-spore datasets sync``):
it needs the same configuration and secrets, and reaches RAGFlow on the internal
network. Output is metadata-only JSON log lines via app.core.logging.log();
the exit status is non-zero when anything failed.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

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
from app.content.tags import load_tags
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
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


async def _crawl(args: argparse.Namespace) -> int:
    settings = get_settings()
    tags = load_tags(settings.config_dir)
    unknown = [tag for tag in args.tag if tag not in tags]
    if unknown:
        raise SystemExit(f"ask-spore crawl: tags not in config/tags.toml: {', '.join(unknown)}")
    async with http_client() as http:
        try:
            report = await crawl(http, args.site_url, args.max_pages)
        except FetchError as exc:
            raise SystemExit(f"ask-spore crawl: {exc}") from None
    for reason, count in sorted(report.skipped.items()):
        log("crawl.skipped", status=reason, chunk_count=count)
    log(
        "crawl.finished",
        level="info" if report.status == "ok" else "error",
        status=report.status,
        chunk_count=len(report.pages),
    )
    if report.status != "ok":
        return 1

    paths = write_pages(
        report.pages, Path(args.out_dir or tempfile.mkdtemp(prefix="ask-spore-crawl-"))
    )
    publisher = args.publisher or (urlsplit(args.site_url).hostname or args.site_url)
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    failed = 0
    try:
        async with RagflowClient.from_settings(settings) as client:
            for page, path in zip(report.pages, paths, strict=True):
                result = await ingest(
                    session_factory(engine),
                    client,
                    tags,
                    SourceFile(path.name, "markdown", page_markdown(page).encode()),
                    SourceMetadata(
                        tags=tuple(args.tag),
                        title=page.title,
                        publisher=publisher,
                        licence_basis=args.licence,
                        canonical_url=page.url,
                    ),
                    parse_timeout=args.parse_timeout,
                )
                _log_ingest(result)
                failed += result.status == "failed"
    finally:
        await engine.dispose()
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
    raise AssertionError("unreachable: argparse enforces the commands")


if __name__ == "__main__":
    raise SystemExit(main())
