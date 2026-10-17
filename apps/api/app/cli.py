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
from collections.abc import Sequence
from datetime import date
from pathlib import Path

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "datasets" and args.datasets_command == "sync":
        return asyncio.run(_datasets_sync())
    if args.command == "ingest":
        return asyncio.run(_ingest(args))
    raise AssertionError("unreachable: argparse enforces the commands")


if __name__ == "__main__":
    raise SystemExit(main())
