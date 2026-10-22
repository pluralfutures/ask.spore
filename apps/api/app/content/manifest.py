"""Corpus manifest (``manifest.csv``) for batch ingestion (P0-11).

Format: ``design/specs/corpus-manifest.md``. ``load_manifest`` validates every row
against ``config/tags.toml`` and the file tree and reports all problems at once;
``run_manifest`` ingests the rows only when there are none. Re-running is safe:
``ingest`` reports a file whose content hash is already ingested as ``duplicate``, or
as ``retagged`` when the row adds tags the source lacks.

Problems name a manifest line and column, never a row's content beyond its path.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from app.content.ingest import SUFFIX_BY_TYPE, TYPE_BY_SUFFIX, IngestResult, SourceMetadata
from app.content.tags import TagConfig

COLUMNS = (
    "path",
    "url",
    "type",
    "tags",
    "title",
    "publisher",
    "published_on",
    "canonical_url",
    "licence_basis",
    "language",
    "max_pages",
    "notes",
)
# P1a-14: an optional column; when absent every row is not downloadable.
OPTIONAL_COLUMNS = ("downloadable",)
DOWNLOADABLE_FILE_TYPES = ("pdf", "docx", "pptx")
_TRUE = ("true", "yes", "1")
_FALSE = ("", "false", "no", "0")
FILE_TYPES = tuple(SUFFIX_BY_TYPE)
SITE = "site"
# Proposed vocabulary (corpus-manifest.md); the research lead may amend it.
LICENCE_BASES = ("public", "open-licence", "publisher-terms", "own-work")
OWN_WORK = "own-work"
DEFAULT_MAX_PAGES = 50
_YEAR = re.compile(r"^\d{4}$")
_LANGUAGE = re.compile(r"^[a-z]{2}$")


class ManifestError(ValueError):
    """The manifest is invalid; ``problems`` lists every one, by line."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("manifest is invalid:\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass(frozen=True)
class ManifestRow:
    line: int  # line number in manifest.csv (header is line 1)
    type: str  # a source type, or "site"
    metadata: SourceMetadata
    path: Path | None = None  # absolute, for files
    url: str | None = None  # for sites
    max_pages: int = DEFAULT_MAX_PAGES


@dataclass(frozen=True)
class RowOutcome:
    line: int
    type: str
    # ingested, duplicate, retagged, failed, and while waiting for a reviewer or the
    # worker proposed, retag_pending or queued; for sites ok, failed or a waiting status
    status: str
    chunk_count: int
    seconds: float
    source_ids: tuple[UUID, ...] = ()
    error_code: str | None = None


def _http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _published_on(value: str) -> date:
    if _YEAR.fullmatch(value):
        return date(int(value), 1, 1)
    return date.fromisoformat(value)  # ValueError when not YYYY-MM-DD


def _row(
    line: int, raw: Mapping[str, str], base: Path, tags_config: Mapping[str, TagConfig]
) -> tuple[ManifestRow | None, list[str]]:
    field = {name: (raw.get(name) or "").strip() for name in (*COLUMNS, *OPTIONAL_COLUMNS)}
    problems: list[str] = []

    def bad(column: str, message: str) -> None:
        problems.append(f"line {line}, {column}: {message}")

    kind = field["type"]
    if kind not in (*FILE_TYPES, SITE):
        bad("type", f"must be one of {', '.join((*FILE_TYPES, SITE))}")

    tags = tuple(dict.fromkeys(t.strip() for t in field["tags"].split(";") if t.strip()))
    if not tags:
        bad("tags", "at least one tag is required")
    unknown = [tag for tag in tags if tag not in tags_config]
    if unknown:
        bad("tags", f"not in config/tags.toml: {', '.join(unknown)}")

    for column in ("title", "publisher"):
        if not field[column]:
            bad(column, "required")

    published_on: date | None = None
    if not field["published_on"]:
        bad("published_on", "required")
    else:
        try:
            published_on = _published_on(field["published_on"])
        except ValueError:
            bad("published_on", "must be YYYY-MM-DD or YYYY")

    licence = field["licence_basis"]
    if licence not in LICENCE_BASES:
        bad("licence_basis", f"must be one of {', '.join(LICENCE_BASES)}")

    canonical_url = field["canonical_url"] or None
    if canonical_url is None and licence != OWN_WORK:
        bad("canonical_url", "required unless licence_basis is own-work")
    elif canonical_url is not None and not _http_url(canonical_url):
        bad("canonical_url", "must be an http(s) URL")

    if field["language"] and not _LANGUAGE.fullmatch(field["language"]):
        bad("language", "must be an ISO 639-1 code such as en")

    path: Path | None = None
    url: str | None = None
    max_pages = DEFAULT_MAX_PAGES
    if kind == SITE:
        if field["path"]:
            bad("path", "must be empty for a site")
        if not _http_url(field["url"]):
            bad("url", "a site needs an http(s) URL")
        url = field["url"]
        if field["max_pages"]:
            try:
                max_pages = int(field["max_pages"])
            except ValueError:
                max_pages = 0
            if max_pages < 1:
                bad("max_pages", "must be a whole number of at least 1")
    elif kind in FILE_TYPES:
        if field["url"]:
            bad("url", "must be empty for a file; use canonical_url for its link")
        if field["max_pages"]:
            bad("max_pages", "only for sites")
        relative = Path(field["path"])
        if not field["path"]:
            bad("path", "required for a file")
        elif relative.is_absolute() or ".." in relative.parts:
            bad("path", "must be relative to the manifest's folder")
        else:
            path = base / relative
            if TYPE_BY_SUFFIX.get(path.suffix.lower()) != kind:
                bad("path", f"file extension does not match type {kind}")
            if not path.is_file():
                bad("path", f"no such file: {field['path']}")

    downloadable = field["downloadable"].lower()
    if downloadable not in (*_TRUE, *_FALSE):
        bad("downloadable", "must be true or false (empty means false)")
    elif downloadable in _TRUE and kind not in DOWNLOADABLE_FILE_TYPES:
        bad("downloadable", "only pdf, docx and pptx files can be downloadable")

    if problems:
        return None, problems
    metadata = SourceMetadata(
        tags=tags,
        title=field["title"],
        publisher=field["publisher"],
        licence_basis=licence,
        published_on=published_on,
        canonical_url=canonical_url,
        downloadable=downloadable in _TRUE,
    )
    return ManifestRow(line, kind, metadata, path, url, max_pages), []


def _header_problems(header: Sequence[str]) -> list[str]:
    """Columns are matched by name, in any order (P0-09, owner decision Oct 20, 2026)."""
    problems: list[str] = []
    missing = [name for name in COLUMNS if name not in header]
    if missing:
        problems.append(f"line 1: header is missing required columns: {', '.join(missing)}")
    unknown = [name for name in header if name not in (*COLUMNS, *OPTIONAL_COLUMNS)]
    if unknown:
        allowed = ", ".join(OPTIONAL_COLUMNS)
        problems.append(
            f"line 1: unknown columns: {', '.join(repr(name) for name in unknown)} "
            f"(the only optional column is {allowed})"
        )
    repeated = sorted({name for name in header if header.count(name) > 1})
    if repeated:
        problems.append(f"line 1: columns listed more than once: {', '.join(repeated)}")
    return problems


def load_manifest(manifest: Path, tags_config: Mapping[str, TagConfig]) -> list[ManifestRow]:
    """Parse and validate the whole manifest; raise ManifestError listing every problem."""
    try:
        text = manifest.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ManifestError([f"cannot read {manifest}: {exc.strerror}"]) from None
    except UnicodeDecodeError:
        raise ManifestError([f"{manifest} is not UTF-8"]) from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [name.strip() for name in reader.fieldnames or ()]
    header_problems = _header_problems(header)
    if header_problems:
        raise ManifestError(header_problems)
    reader.fieldnames = header

    base = manifest.parent
    rows: list[ManifestRow] = []
    problems: list[str] = []
    seen_names: dict[str, int] = {}
    seen_urls: dict[str, int] = {}
    for raw in reader:
        line = reader.line_num
        if None in raw:
            problems.append(f"line {line}: more fields than the header")
            continue
        if not any((value or "").strip() for value in raw.values()):
            continue  # blank line
        row, row_problems = _row(line, raw, base, tags_config)
        problems += row_problems
        if row is None:
            continue
        if row.path is not None:
            first = seen_names.setdefault(row.path.name.lower(), line)
            if first != line:
                problems.append(f"line {line}, path: file name already used on line {first}")
        if row.url is not None:
            first = seen_urls.setdefault(row.url.rstrip("/"), line)
            if first != line:
                problems.append(f"line {line}, url: site already listed on line {first}")
        rows.append(row)
    if problems:
        raise ManifestError(problems)
    if not rows:
        raise ManifestError([f"{manifest} has no rows"])
    return rows


IngestFile = Callable[[ManifestRow], Awaitable[IngestResult]]
CrawlSite = Callable[[ManifestRow], Awaitable[tuple[str, list[IngestResult]]]]


# Per-page statuses that make a site row wait, in order of precedence after "failed".
_SITE_WAITING = ("proposed", "retag_pending", "queued")


def row_outcome(
    row: ManifestRow,
    results: Sequence[IngestResult],
    seconds: float,
    crawl_status: str | None = None,
) -> RowOutcome:
    """The summary line for one row: its file's result, or its site's pages together.

    ``seconds`` is the time the row took to submit; each result adds its job's run time
    once the CLI has waited for it (``--wait``).
    """
    seconds += sum(r.seconds for r in results)
    if row.type != SITE:
        [result] = results
        return RowOutcome(
            line=row.line,
            type=row.type,
            status=result.status,
            chunk_count=result.chunk_count,
            seconds=seconds,
            source_ids=(result.source_id,),
            error_code=result.error_code,
        )
    failed = [r for r in results if r.status == "failed"]
    if crawl_status != "ok" or failed:
        status = "failed"
    else:
        statuses = {r.status for r in results}
        status = next((s for s in _SITE_WAITING if s in statuses), "ok")
    return RowOutcome(
        line=row.line,
        type=row.type,
        status=status,
        chunk_count=sum(r.chunk_count for r in results),
        seconds=seconds,
        source_ids=tuple(r.source_id for r in results),
        error_code=crawl_status
        if crawl_status != "ok"
        else (failed[0].error_code if failed else None),
    )


async def run_manifest(
    rows: Sequence[ManifestRow],
    ingest_file: IngestFile,
    crawl_site: CrawlSite,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> list[RowOutcome]:
    """Submit each validated row in order; one row failing does not stop the others."""
    outcomes: list[RowOutcome] = []
    for row in rows:
        started = clock()
        if row.type == SITE:
            status, results = await crawl_site(row)
            outcomes.append(row_outcome(row, results, clock() - started, status))
        else:
            result = await ingest_file(row)
            outcomes.append(row_outcome(row, [result], clock() - started))
    return outcomes


def write_summary(outcomes: Sequence[RowOutcome], path: Path) -> None:
    """The summary table as CSV: one row per manifest line, no titles or content."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["line", "type", "status", "chunk_count", "seconds", "source_ids", "error_code"]
        )
        for o in outcomes:
            writer.writerow(
                [
                    o.line,
                    o.type,
                    o.status,
                    o.chunk_count,
                    f"{o.seconds:.1f}",
                    ";".join(str(s) for s in o.source_ids),
                    o.error_code or "",
                ]
            )
