"""Uploaded crawls (P2SR01-02): inspect and stage a ZIP of Markdown pages.

A content editor uploads one ZIP per site: one crawl of one domain, made outside the
platform and converted to Markdown (markdown.new, Cloudflare's Markdown for Agents), with
the crawl date, full or partial (D5) and the declaration that the crawl honoured the
site's robots.txt, TDM reservation and page-level directives (D3). ``inspect_zip`` reads
the ZIP member by member and judges each one; ``stage_upload`` refuses or stages it and
records a ``site_uploads`` row (``staged``) for a reviewer to release
(``app.content.uploadcrawl``).

The ZIP (spec "The ZIP"):

- read from memory or a path, member by member, never extracted to a directory; each
  member's uncompressed bytes are counted as they are read, so a ZIP that declares a
  false size is still held to the caps (``MAX_MEMBER_BYTES`` per member,
  ``MAX_TOTAL_BYTES`` in all);
- a member that is absolute, contains ``..``, is a symbolic link, is encrypted, or is
  itself an archive refuses the whole upload (``unsafe_member``), as do two accepted
  members with the same normalised URL (``duplicate_url``), more than ``MAX_MEMBERS``
  Markdown members (``too_many_members``) and no accepted member at all (``no_pages``);
- directories, hidden entries (``.DS_Store``, ``__MACOSX/``) and files that are not
  ``.md`` or ``.markdown`` are ``skipped_not_markdown``;
- a Markdown member is UTF-8 (a BOM allowed) and starts with the ``<!-- Source: <url> -->``
  comment, a front-matter block, or both in that order. The block is read by the
  restricted parser below, not a YAML library: top-level ``key: value`` scalars (plain or
  quoted) and keys whose value is an indented block, which is skipped uninterpreted.
  Only ``url``, ``title`` and ``date`` are read; everything else (markdown.new's nested
  ``meta`` mapping included) is dropped with the block. A member that fails a rule is
  refused on its own with a code, and the rest of the upload goes on.

The body without the comment and the block is what is staged and hashed, as the live
crawler stages a rendered page (``app.content.sitecrawl``), so a change to the front
matter alone is not a changed page. It is taken as supplied (D11): no readability pass.

Member names, URLs and titles are returned only in the report, for the editor's screen;
log lines, audit events, the ``site_uploads`` row and a whole-upload refusal carry
identifiers, codes, counts and the offending member's index only.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.content.crawler import Scope, _same_site, normalise
from app.content.fetch import Resolver, resolve_host
from app.content.models import UPLOAD_MODES, Site, SitePage, SiteUpload
from app.content.register import RegisterError
from app.content.roles import EDITOR, require
from app.content.sites import ORIGIN_UPLOAD, SiteSpec, register_in
from app.content.special import special_category, whitelisted
from app.content.store import stage_upload_zip
from app.content.tags import TagConfig
from app.core.db import tenant_session
from app.core.logging import log
from app.tenancy.models import INTERNAL_TENANT_ID

# D6: limits of one upload.
MAX_ZIP_BYTES: Final = 200 * 1024 * 1024
MAX_MEMBERS: Final = 2000  # Markdown members
MAX_MEMBER_BYTES: Final = 5 * 1024 * 1024  # uncompressed, per member
MAX_TOTAL_BYTES: Final = 500 * 1024 * 1024  # uncompressed, all Markdown members
# Entries of any kind in the central directory (not in the spec: a bound on what the
# ZIP's directory alone makes us hold in memory; 2,000 pages plus their folders and
# a converter's side files fit many times over).
MAX_ENTRIES: Final = 20000
MAX_URL_LENGTH: Final = 2000
MAX_TITLE_LENGTH: Final = 500
MARKDOWN_SUFFIXES: Final = frozenset({".md", ".markdown"})
ARCHIVE_SUFFIXES: Final = frozenset(
    ".zip .gz .tgz .tar .bz2 .xz .7z .rar .zst .jar .war .ear .cab .lz .lzma".split()
)
_ARCHIVE_MAGIC: Final = (b"PK\x03\x04", b"\x1f\x8b", b"7z\xbc\xaf", b"Rar!", b"BZh", b"\xfd7zXZ")
_READ_CHUNK: Final = 64 * 1024

# Whole-upload refusals (422 with the code and the member index).
WHOLE_UPLOAD_CODES: Final = frozenset(
    {
        "not_a_zip",
        "unsafe_member",
        "duplicate_url",
        "too_many_members",
        "total_too_large",
        "no_pages",
    }
)
# Per-member outcomes.
ACCEPTED: Final = "accepted"
SKIPPED: Final = "skipped_not_markdown"
MEMBER_CODES: Final = frozenset(
    {
        "url_missing",
        "url_mismatch",
        "bad_url",
        "off_site",
        "bad_date",
        "front_matter_invalid",
        "empty",
        "not_utf8",
        "member_too_large",
    }
)

_SOURCE_COMMENT = re.compile(r"^<!--\s*Source:\s*(\S+)\s*-->\s*$", re.IGNORECASE)
_KEY_LINE = re.compile(r"^([a-z][a-z0-9_-]*)\s*:(?:[ \t]+(.*?))?\s*$")
_DOUBLE = re.compile(r'^"((?:[^"\\]|\\.)*)"(?:\s+#.*)?$')
_SINGLE = re.compile(r"^'((?:[^']|'')*)'(?:\s+#.*)?$")
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ESCAPES: Final = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "b": "\b",
    "f": "\f",
}
_WANTED: Final = frozenset({"url", "title", "date"})


def declaration_text(host: str, crawled_on: str) -> str:
    """The declaration the uploader makes (owner decision 2, Oct 31, 2026), word for word;
    the console's checkbox shows the same sentence (``apps/web/src/lib/content.ts``)."""
    return (
        f"I confirm that this crawl of {host or '<host>'} was made on "
        f"{crawled_on or '<crawled_on>'} honouring the site's robots.txt, its "
        "text-and-data-mining reservation if any, and page-level noai and noindex "
        "directives, and that the pages are public and were fetched without signing in."
    )


class UploadRefused(Exception):
    """The whole upload is refused. ``code`` and ``member`` (an index, or None) are safe
    to log and to return; never a member's name."""

    def __init__(self, code: str, member: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.member = member


class _MemberRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Page:
    """An accepted member: what the import makes a page of."""

    url: str
    title: str
    published_on: date | None
    markdown: str  # the body without the comment and the block, stripped


@dataclass(frozen=True)
class MemberReport:
    index: int
    name: str  # the member's name in the ZIP: the editor's own, shown once, never logged
    outcome: str  # accepted, skipped_not_markdown or a member code
    url: str | None = None
    title: str | None = None
    published_on: date | None = None
    # For an accepted member, why the import will block it (special_category,
    # out_of_scope), with the special category.
    note: str | None = None
    special_category: str | None = None


@dataclass(frozen=True)
class UploadReport:
    members: tuple[MemberReport, ...]
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def accepted_urls(self) -> frozenset[str]:
        return frozenset(m.url for m in self.members if m.outcome == ACCEPTED and m.url)

    @property
    def accepted(self) -> int:
        return sum(m.outcome == ACCEPTED for m in self.members)

    @property
    def skipped(self) -> int:
        return sum(m.outcome == SKIPPED for m in self.members)

    @property
    def refused(self) -> int:
        return len(self.members) - self.accepted - self.skipped


# --- the front matter ----------------------------------------------------------------------


def _unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char != "\\":
            out.append(char)
            i += 1
            continue
        nxt = value[i + 1 : i + 2]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", value[i + 2 : i + 6]):
            out.append(chr(int(value[i + 2 : i + 6], 16)))
            i += 6
        else:
            raise _MemberRefused("front_matter_invalid")
    return "".join(out)


def _scalar(value: str) -> str:
    """A plain, single- or double-quoted scalar; anything else is refused."""
    if match := _DOUBLE.match(value):
        return _unescape(match[1])
    if match := _SINGLE.match(value):
        return match[1].replace("''", "'")
    if not value or value[0] in "\"'[]{}|>&*!%@`#":
        raise _MemberRefused("front_matter_invalid")
    plain = re.sub(r"\s+#.*$", "", value).strip()
    if not plain or plain.endswith(":"):
        raise _MemberRefused("front_matter_invalid")
    return plain


def _block(lines: list[str]) -> dict[str, str]:
    """The wanted keys of a front-matter block (the lines between the ``---`` lines)."""
    found: dict[str, str] = {}
    nested = False  # inside the indented block of the key above
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t" or (nested and line.startswith("- ")):
            if not nested:
                raise _MemberRefused("front_matter_invalid")
            continue  # e.g. markdown.new's ``meta:`` mapping: skipped, never read
        match = _KEY_LINE.match(line)
        if match is None:
            raise _MemberRefused("front_matter_invalid")
        key, value = match[1], match[2] or ""
        # An indented block follows: a mapping or list, or a literal or folded scalar.
        nested = value == "" or re.fullmatch(r"[|>][-+0-9]*(\s+#.*)?", value) is not None
        if key not in _WANTED:
            continue  # ignored and dropped with the block
        if key in found or value == "":
            raise _MemberRefused("front_matter_invalid")
        found[key] = _scalar(value)
    return found


def _url(raw: str, host: str) -> str:
    url = raw.strip()
    parts = urlsplit(url)
    if len(url) > MAX_URL_LENGTH or parts.scheme not in ("http", "https") or not parts.hostname:
        raise _MemberRefused("bad_url")
    url = normalise(url)
    if not _same_site(url, host):
        raise _MemberRefused("off_site")
    return url


def _date(raw: str) -> date:
    match = _ISO_DAY.match(raw)
    if match is None:
        raise _MemberRefused("bad_date")
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        raise _MemberRefused("bad_date") from None


def _clean_title(title: str) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in title).split())


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip().rstrip("#").strip()
    return ""


def parse_page(text: str, host: str) -> Page:
    """One Markdown member's page: the URL from the ``Source`` comment or the ``url`` key
    (both must agree), the title, the explicit publication date and the body. Raises
    ``_MemberRefused`` with the member code."""
    lines = text.removeprefix("\ufeff").splitlines()
    i = 0

    def skip_blank() -> None:
        nonlocal i
        while i < len(lines) and not lines[i].strip():
            i += 1

    skip_blank()
    source: str | None = None
    if i < len(lines) and (match := _SOURCE_COMMENT.match(lines[i].strip())):
        source = match[1]
        i += 1
        skip_blank()
    keys: dict[str, str] = {}
    if i < len(lines) and lines[i].rstrip() == "---":
        try:
            end = next(j for j in range(i + 1, len(lines)) if lines[j].rstrip() == "---")
        except StopIteration:
            raise _MemberRefused("front_matter_invalid") from None
        keys = _block(lines[i + 1 : end])
        i = end + 1
    if source is None and "url" not in keys:
        raise _MemberRefused("url_missing")
    url = _url(source if source is not None else keys["url"], host)
    if source is not None and "url" in keys and _url(keys["url"], host) != url:
        raise _MemberRefused("url_mismatch")
    published = _date(keys["date"]) if "date" in keys else None
    markdown = "\n".join(lines[i:]).strip()
    if not markdown:
        raise _MemberRefused("empty")
    title = _clean_title(keys.get("title", "")) or _first_heading(markdown)
    title = _clean_title(title) or urlsplit(url).path or url
    return Page(url, title[:MAX_TITLE_LENGTH], published, markdown)


# --- the ZIP -----------------------------------------------------------------------------


def _unsafe(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    parts = PurePosixPath(name.replace("\\", "/")).parts
    mode = (info.external_attr >> 16) & 0o170000
    return (
        name.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", name) is not None
        or ".." in parts
        or "\0" in name
        or mode == 0o120000  # a symbolic link
        or bool(info.flag_bits & 0x1)  # encrypted
        or PurePosixPath(name.lower()).suffix in ARCHIVE_SUFFIXES
    )


def _hidden(info: zipfile.ZipInfo) -> bool:
    parts = PurePosixPath(info.filename.replace("\\", "/")).parts
    return any(p.startswith(".") or p == "__MACOSX" for p in parts)


def _read_capped(archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: int) -> bytes | None:
    """The member's uncompressed bytes, counted as they are read; None when over the
    per-member cap. Raises UploadRefused when the upload's total runs out."""
    out = bytearray()
    with archive.open(info) as handle:
        while chunk := handle.read(_READ_CHUNK):
            out += chunk
            if len(out) > budget:
                raise UploadRefused("total_too_large")
            if len(out) > MAX_MEMBER_BYTES:
                return None
    return bytes(out)


def _members(source: Path | bytes, host: str) -> Iterator[tuple[MemberReport, Page | None]]:
    """Every member's report and, for an accepted one, its page; in ZIP order."""
    try:
        handle: io.BufferedIOBase = (
            io.BytesIO(source) if isinstance(source, bytes) else source.open("rb")
        )
    except OSError:
        raise UploadRefused("upload_missing") from None
    with handle:
        try:
            archive = zipfile.ZipFile(handle)
        except (zipfile.BadZipFile, OSError, ValueError):
            raise UploadRefused("not_a_zip") from None
        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise UploadRefused("too_many_members")
            for index, info in enumerate(infos):
                if _unsafe(info):
                    raise UploadRefused("unsafe_member", index)
            markdown = 0
            budget = MAX_TOTAL_BYTES
            for index, info in enumerate(infos):
                name = info.filename
                suffix = PurePosixPath(name.lower()).suffix
                if info.is_dir() or _hidden(info) or suffix not in MARKDOWN_SUFFIXES:
                    yield MemberReport(index, name, SKIPPED), None
                    continue
                markdown += 1
                if markdown > MAX_MEMBERS:
                    raise UploadRefused("too_many_members", index)
                try:
                    content = _read_capped(archive, info, budget)
                except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError):
                    raise UploadRefused("not_a_zip", index) from None
                except RuntimeError:  # zipfile's "encrypted, password required"
                    raise UploadRefused("unsafe_member", index) from None
                except UploadRefused as exc:
                    raise UploadRefused(exc.code, index) from None
                if content is None:
                    budget -= MAX_MEMBER_BYTES
                    yield MemberReport(index, name, "member_too_large"), None
                    continue
                budget -= len(content)
                if content.startswith(_ARCHIVE_MAGIC):
                    raise UploadRefused("unsafe_member", index)  # an archive named .md
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    yield MemberReport(index, name, "not_utf8"), None
                    continue
                if "\0" in text:
                    yield MemberReport(index, name, "not_utf8"), None
                    continue
                try:
                    page = parse_page(text, host)
                except _MemberRefused as exc:
                    yield MemberReport(index, name, exc.code), None
                    continue
                yield (
                    MemberReport(index, name, ACCEPTED, page.url, page.title, page.published_on),
                    page,
                )


def inspect_zip(
    source: Path | bytes,
    *,
    host: str,
    special: Callable[[str, str], str | None] | None = None,
    scope: Scope | None = None,
) -> UploadReport:
    """Judge every member of the ZIP (see the module docstring); reads nothing into
    RAGFlow and writes nothing. ``special`` and ``scope`` note the accepted members the
    import will block. Raises UploadRefused for a whole-upload refusal."""
    reports: list[MemberReport] = []
    seen: set[str] = set()
    for report, page in _members(source, host):
        if page is not None:
            if page.url in seen:
                raise UploadRefused("duplicate_url", report.index)
            seen.add(page.url)
            if scope is not None and not scope.admits(page.url):
                report = replace(report, note="out_of_scope")
            elif special is not None and (category := special(page.url, page.title)):
                report = replace(report, note="special_category", special_category=category)
        reports.append(report)
    if not seen:
        raise UploadRefused("no_pages")
    counts = Counter(r.outcome for r in reports)
    return UploadReport(tuple(reports), dict(counts))


def pages(source: Path | bytes, *, host: str) -> Iterator[Page]:
    """The accepted pages, one at a time (the import; call ``inspect_zip`` first)."""
    for _, page in _members(source, host):
        if page is not None:
            yield page


def special_for(site: Site | None) -> Callable[[str, str], str | None]:
    allow = list(site.special_category_allow) if site is not None else []

    def special(url: str, title: str) -> str | None:
        return None if whitelisted(url, allow) else special_category(url, title)

    return special


def scope_of(site: Site | None) -> Scope | None:
    if site is None or not (site.allow_patterns or site.deny_patterns):
        return None
    return Scope(tuple(site.allow_patterns), tuple(site.deny_patterns))


# --- staging -----------------------------------------------------------------------------


@dataclass(frozen=True)
class StagedUpload:
    upload_id: UUID
    site_id: UUID
    report: UploadReport
    would_withdraw: int | None  # full mode: live pages absent from the ZIP


async def live_urls(session: AsyncSession, site_id: UUID) -> set[str]:
    return set(
        await session.scalars(
            select(SitePage.url).where(SitePage.site_id == site_id, SitePage.state == "live")
        )
    )


def check_upload(*, crawled_on: date, mode: str, declared: bool, today: date | None) -> None:
    if not declared:
        raise RegisterError("declaration_required")
    if mode not in UPLOAD_MODES:
        raise RegisterError("bad_mode")
    if crawled_on > (today or datetime.now(UTC).date()):
        raise RegisterError("crawled_in_future")


async def stage_upload(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    content: bytes,
    *,
    content_root: Path,
    uploader_id: UUID | None,
    crawled_on: date,
    mode: str,
    declared: bool,
    site_id: UUID | None = None,
    spec: SiteSpec | None = None,
    resolve: Resolver = resolve_host,
    today: date | None = None,
) -> StagedUpload:
    """An editor's upload, for an existing upload site (``site_id``) or a new one
    (``spec``, registered ``proposed`` with ``origin = 'upload'`` in the same
    transaction). ``uploader_id`` must hold ``content_editor``; None is the operator's
    shell (the CLI). Raises RegisterError, RoleError, FetchError (a start URL that is not
    public) or UploadRefused. Audited ``site.upload_staged`` with counts only."""
    check_upload(crawled_on=crawled_on, mode=mode, declared=declared, today=today)
    if len(content) > MAX_ZIP_BYTES:
        raise UploadRefused("zip_too_large")
    if site_id is not None and spec is not None:
        raise ValueError("an upload names a site or registers one, not both")
    if uploader_id is not None:
        async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
            await require(session, uploader_id, EDITOR)
    site: Site | None = None
    if site_id is not None:
        async with factory() as session:
            site = await session.get(Site, site_id)
        if site is None:
            raise RegisterError("no_site")
        _check_site(site)
        host = site.host
    elif spec is not None:
        host = urlsplit(normalise(spec.start_url.strip())).hostname or ""
    else:
        raise ValueError("an upload names a site or registers one")
    report = inspect_zip(content, host=host, special=special_for(site), scope=scope_of(site))

    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        if spec is not None:
            site_id, created = await register_in(
                session,
                tags_config,
                replace(spec, origin="upload", schedule="none"),
                proposer_id=uploader_id,
                resolve=resolve,
            )
            if not created:
                raise RegisterError("site_exists")
        if site_id is None:
            raise ValueError("an upload names a site or registers one")
        locked = await session.scalar(select(Site).where(Site.id == site_id).with_for_update())
        if locked is None:
            raise RegisterError("no_site")
        _check_site(locked)
        pending = await session.scalar(
            select(func.count())
            .select_from(SiteUpload)
            .where(SiteUpload.site_id == site_id, SiteUpload.status.in_(("staged", "queued")))
        )
        if pending:
            raise RegisterError("upload_pending")
        sha, staged = stage_upload_zip(content_root, content)
        upload_id = await session.scalar(
            insert(SiteUpload)
            .values(
                site_id=site_id,
                uploaded_by=uploader_id,
                crawled_on=crawled_on,
                mode=mode,
                declared_robots_honoured=True,
                zip_sha256=sha,
                staged_path=staged,
                member_count=len(report.members),
                accepted_count=report.accepted,
                refused_count=report.refused,
                skipped_count=report.skipped,
            )
            .returning(SiteUpload.id)
        )
        if upload_id is None:
            raise AssertionError("the insert returns the new row's ID")
        would = None
        if mode == "full":
            would = len(await live_urls(session, site_id) - report.accepted_urls)
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=uploader_id,
            event="site.upload_staged",
            metadata={
                "upload_id": str(upload_id),
                "site_id": str(site_id),
                "mode": mode,
                "method": "cli" if uploader_id is None else "editor",
                "members": len(report.members),
                "accepted": report.accepted,
                "refused": report.refused,
                "skipped": report.skipped,
            },
        )
    log(
        "content.upload_staged",
        upload_id=str(upload_id),
        site_id=str(site_id),
        status="staged",
        count=report.accepted,
    )
    staged_id: UUID = upload_id
    return StagedUpload(staged_id, site_id, report, would)


def _check_site(site: Site) -> None:
    if site.origin != "upload":
        raise RegisterError("origin_crawl")
    if site.status in ("withdrawn", "rejected"):
        raise RegisterError("site_withdrawn" if site.status == "withdrawn" else "site_rejected")


__all__ = [
    "ACCEPTED",
    "MAX_ZIP_BYTES",
    "ORIGIN_UPLOAD",
    "SKIPPED",
    "MemberReport",
    "Page",
    "StagedUpload",
    "UploadRefused",
    "UploadReport",
    "inspect_zip",
    "pages",
    "parse_page",
    "stage_upload",
]
