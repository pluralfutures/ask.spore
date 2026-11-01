"""P2SR01: uploaded crawls. Upload sites, the ZIP inspection, release and the
``import_crawl`` job, against PostgreSQL and a fake RAGFlow. Synthetic pages only
(``packages/eval/fixtures/uploads/``)."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from pydantic import SecretStr
from sqlalchemy import text as sql

from app import cli
from app.chat.package import provenance_by_document, workspace_package
from app.content.crawler import HostLimiter, Scope
from app.content.jobs import JOB_TYPES, PAYLOAD_KEYS, enqueue
from app.content.register import RegisterError, pause, record_takedown, request_withdrawal
from app.content.roles import RoleError
from app.content.sitecrawl import crawl_site
from app.content.sites import (
    SiteSettings,
    SiteSpec,
    approve_site,
    register_site,
    request_crawl,
    schedule_due_crawls,
    set_special_category_allow,
    update_site,
)
from app.content.uploadcrawl import reject_upload, release_upload, upload_report
from app.content.uploads import (
    Page,
    StagedUpload,
    UploadRefused,
    _MemberRefused,
    inspect_zip,
    pages,
    parse_page,
    special_for,
    stage_upload,
)
from app.core.config import load_settings
from app.core.db import tenant_session
from app.files.service import FileRefused, issue_link, workspace_files
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase, _admin_dsn, _execute, _with_database, migrate
from tests.test_crawler import ROOT, resolver
from tests.test_datasets_sync import ENV
from tests.test_ingest import TAGS, content_user, env, source_row
from tests.test_pause import REASON
from tests.test_pause_pipeline import web_tenant
from tests.test_sites import PUBLIC, Crawls, crawls
from tests.test_withdraw import cite, flags, other_tenant

__all__ = ["crawls", "env"]  # the fixtures, imported for their use here


async def upload_site(c: Crawls, **overrides: Any) -> UUID:
    fields: dict[str, Any] = {
        "start_url": ROOT + "/",
        "name": "Synthetic Food Co",
        "publisher": "Synthetic Food Co",
        "licence_basis": "publisher-terms",
        "tags": ("sample-web",),
        "origin": "upload",
    }
    spec = SiteSpec(**(fields | overrides))
    site_id, created = await register_site(
        c.e.factory, TAGS, spec, proposer_id=c.e.user_id, resolve=resolver(PUBLIC)
    )
    assert created
    return site_id


# --- P2SR01-01 register: upload sites ----------------------------------------------------


async def test_an_upload_site_is_never_crawled_scheduled_or_approved_by_a_crawl(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    site_id = await upload_site(crawls)
    row = await crawls.site_row(site_id)
    assert (row["origin"], row["schedule"], row["next_crawl_at"]) == ("upload", "none", None)
    proposed = await crawls.events("site.proposed", site_id)
    assert proposed[0]["after"]["origin"] == "upload"
    # Approval comes with the release of the first upload, not with a crawl.
    with pytest.raises(RegisterError, match="origin_upload"):
        await approve_site(crawls.e.factory, site_id, crawls.e.user_id)
    await admin_conn.execute(
        "UPDATE sites SET status = 'approved', approved_at = now(), approved_by = $2 WHERE id = $1",
        site_id,
        crawls.e.user_id,
    )
    with pytest.raises(RegisterError, match="origin_upload"):
        await request_crawl(crawls.e.factory, site_id, crawls.e.user_id)
    with pytest.raises(RegisterError, match="origin_upload"):
        await update_site(
            crawls.e.factory, site_id, crawls.e.user_id, SiteSettings((), (), "weekly", 50)
        )
    # Scope rules and the page budget may still change; the schedule stays none.
    await update_site(
        crawls.e.factory, site_id, crawls.e.user_id, SiteSettings(("/p/*",), (), "none", 50)
    )
    assert await schedule_due_crawls(crawls.e.factory) == 0
    # A crawl job queued by hand is refused by the job itself.
    result = await crawl_site(
        crawls.e.factory,
        site_id,
        content_root=crawls.e.content_root,
        limiter=HostLimiter(),
        resolve=resolver(PUBLIC),
    )
    assert (result.status, result.error_code) == ("refused", "origin_upload")
    assert not crawls.site.requested  # nothing was fetched
    count = await admin_conn.fetchval("SELECT count(*) FROM jobs WHERE type = 'crawl_site'")
    assert count == 0


async def test_an_upload_site_cannot_be_registered_with_a_schedule(crawls: Crawls) -> None:
    with pytest.raises(RegisterError, match="origin_upload"):
        await upload_site(crawls, schedule="weekly")
    with pytest.raises(RegisterError, match="bad_origin"):
        await upload_site(crawls, origin="manual")


async def test_the_database_holds_an_upload_site_to_its_rules(
    crawls: Crawls, admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    crawled = await crawls.register()
    uploaded = await upload_site(crawls, start_url="https://site.example/other")
    assert (await crawls.site_row(crawled))["origin"] == "crawl"  # the default
    # The origin is fixed at creation.
    with pytest.raises(asyncpg.CheckViolationError, match="origin is fixed"):
        await admin_conn.execute("UPDATE sites SET origin = 'upload' WHERE id = $1", crawled)
    with pytest.raises(asyncpg.CheckViolationError, match="origin is fixed"):
        await admin_conn.execute("UPDATE sites SET origin = 'crawl' WHERE id = $1", uploaded)
    with pytest.raises(asyncpg.CheckViolationError, match="upload_unscheduled"):
        await admin_conn.execute("UPDATE sites SET schedule = 'weekly' WHERE id = $1", uploaded)
    with pytest.raises(asyncpg.CheckViolationError, match="upload_unscheduled"):
        await admin_conn.execute("UPDATE sites SET next_crawl_at = now() WHERE id = $1", uploaded)
    with pytest.raises(asyncpg.CheckViolationError, match="origin_valid"):
        await admin_conn.execute(
            "INSERT INTO sites (start_url, host, name, publisher, licence_basis, tags, origin) "
            "VALUES ('https://x.example/', 'x.example', 'n', 'p', 'l', '{sample-web}', 'fetch')"
        )
    await admin_conn.execute("UPDATE sites SET allow_decision = 'declared' WHERE id = $1", uploaded)

    async def upload(**values: Any) -> None:
        columns = {
            "site_id": uploaded,
            "crawled_on": "2026-10-30",
            "declared_robots_honoured": True,
            "zip_sha256": "a" * 64,
        } | values
        names = ", ".join(columns)
        params = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        args = [date.fromisoformat(v) if k == "crawled_on" else v for k, v in columns.items()]
        await app_conn.execute(f"INSERT INTO site_uploads ({names}) VALUES ({params})", *args)

    for values, constraint in (
        ({"declared_robots_honoured": False}, "declaration_made"),
        ({"crawled_on": "2999-01-01"}, "crawled_not_after_upload"),
        ({"mode": "some"}, "mode_valid"),
        ({"zip_sha256": "not-a-hash"}, "zip_sha256_hex"),
        ({"staged_path": "elsewhere/" + "a" * 64 + ".zip"}, "staged_by_hash"),
        ({"status": "queued"}, "release_recorded"),
        ({"status": "rejected"}, "rejection_noted"),
        ({"status": "failed"}, "error_when_failed"),
        ({"error": "Synthetic error text"}, "error_when_failed"),
        ({"new_count": -1}, "counts_non_negative"),
    ):
        with pytest.raises(asyncpg.CheckViolationError, match=constraint):
            await upload(**values)
    await upload(staged_path="uploads/" + "a" * 64 + ".zip")
    with pytest.raises(asyncpg.UniqueViolationError, match="one_pending_per_site"):
        await upload()  # D10: one pending upload per site
    await admin_conn.execute("UPDATE site_uploads SET status = 'rejected', review_note = 'x'")
    await upload()  # the earlier one no longer pending
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM site_uploads")


async def test_the_job_catalogue_knows_import_crawl(
    crawls: Crawls, admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    assert "import_crawl" in JOB_TYPES
    assert "upload_id" in PAYLOAD_KEYS
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    async with tenant_session(crawls.e.factory, INTERNAL_TENANT_ID) as session:
        a = await enqueue(session, "import_crawl", {"upload_id": first}, created_by=None)
        again = await enqueue(session, "import_crawl", {"upload_id": first}, created_by=None)
        b = await enqueue(session, "import_crawl", {"upload_id": second}, created_by=None)
    assert a == again and a != b  # one active job per upload
    with pytest.raises(asyncpg.CheckViolationError, match="import_names_upload"):
        await app_conn.execute("INSERT INTO jobs (type, payload) VALUES ('import_crawl', '{}')")
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'import_crawl'")


def test_migration_0080_defaults_existing_sites_to_crawl_and_round_trips() -> None:
    admin = _admin_dsn()
    if admin is None:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set")
    name = f"askspore_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_execute(admin, f'CREATE DATABASE "{name}"'))
    db = MigratedDatabase(dsn=_with_database(admin, name))

    async def fetch(sql: str) -> list[asyncpg.Record]:
        conn = await asyncpg.connect(db.dsn)
        try:
            return list(await conn.fetch(sql))
        finally:
            await conn.close()

    try:
        migrate(db, "0065")
        asyncio.run(
            _execute(
                db.dsn,
                "INSERT INTO sites (start_url, host, name, publisher, licence_basis, tags, "
                "schedule) VALUES ('https://a.example/', 'a.example', 'A', 'A', 'l', "
                "'{sample-web}', 'weekly')",
            )
        )
        migrate(db, "0080")
        rows = asyncio.run(fetch("SELECT origin, schedule, allow_decision FROM sites"))
        assert [tuple(r) for r in rows] == [("crawl", "weekly", "unchecked")]
        asyncio.run(
            _execute(
                db.dsn,
                "INSERT INTO sites (start_url, host, name, publisher, licence_basis, tags, "
                "origin, allow_decision) VALUES ('https://b.example/', 'b.example', 'B', 'B', "
                "'l', '{sample-web}', 'upload', 'declared');"
                "INSERT INTO site_uploads (site_id, crawled_on, declared_robots_honoured, "
                "zip_sha256) SELECT id, '2026-10-30', true, repeat('b', 64) FROM sites "
                "WHERE origin = 'upload';"
                "INSERT INTO jobs (type, payload) SELECT 'import_crawl', "
                "jsonb_build_object('upload_id', id::text) FROM site_uploads",
            )
        )
        migrate(db, "0065", down=True)
        rows = asyncio.run(fetch("SELECT allow_decision FROM sites ORDER BY start_url"))
        assert [r["allow_decision"] for r in rows] == ["unchecked", "unchecked"]
        jobs = asyncio.run(fetch("SELECT type FROM jobs"))
        assert jobs == []
        migrate(db, "0080")
    finally:
        asyncio.run(_execute(admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


# --- P2SR01-02 inspection ----------------------------------------------------------------

UPLOADS = Path(__file__).resolve().parents[3] / "packages" / "eval" / "fixtures" / "uploads"
HOST = "www.example.org"


def fixture(name: str) -> bytes:
    return (UPLOADS / name).read_bytes()


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("off-site.zip", "off_site"),
        ("url-missing.zip", "url_missing"),
        ("bad-date.zip", "bad_date"),
        ("url-mismatch.zip", "url_mismatch"),
        ("unterminated-block.zip", "front_matter_invalid"),
        ("empty-body.zip", "empty"),
        ("not-utf8.zip", "not_utf8"),
        ("oversize-member.zip", "member_too_large"),
    ],
)
def test_a_member_that_breaks_a_rule_is_refused_alone_with_its_code(name: str, code: str) -> None:
    report = inspect_zip(UPLOADS / name, host=HOST)
    outcomes = [m.outcome for m in report.members]
    assert outcomes == ["accepted", code]
    refused = report.members[1]
    assert (refused.url, refused.title) == (None, None)  # nothing read from it is kept
    assert (report.accepted, report.refused, report.skipped) == (1, 1, 0)
    # The same bytes from memory give the same report.
    assert inspect_zip(fixture(name), host=HOST) == report


@pytest.mark.parametrize(
    ("name", "code", "member"),
    [
        ("dotdot-name.zip", "unsafe_member", 1),
        ("absolute-name.zip", "unsafe_member", 1),
        ("nested-zip.zip", "unsafe_member", 1),
        ("zip-named-md.zip", "unsafe_member", 1),
        ("symlink.zip", "unsafe_member", 1),
        ("encrypted.zip", "unsafe_member", 1),
        ("duplicate-url.zip", "duplicate_url", 1),
        ("no-pages.zip", "no_pages", None),
        ("not-a-zip.zip", "not_a_zip", None),
    ],
)
def test_a_whole_upload_refusal_names_the_code_and_the_member_index(
    name: str, code: str, member: int | None
) -> None:
    with pytest.raises(UploadRefused) as refused:
        inspect_zip(UPLOADS / name, host=HOST)
    assert (refused.value.code, refused.value.member) == (code, member)
    assert str(refused.value) == code  # never a member name


def test_a_file_exactly_as_markdown_new_emits_it_is_accepted_without_its_front_matter() -> None:
    report = inspect_zip(UPLOADS / "markdown-new.zip", host=HOST)
    assert [(m.name, m.outcome) for m in report.members] == [
        ("site/", "skipped_not_markdown"),
        ("site/Products/Gravies.md", "accepted"),
        ("site/Products/Broth.md", "accepted"),
        ("site/Recipes/Soup.markdown", "accepted"),
        ("site/.DS_Store", "skipped_not_markdown"),
        ("__MACOSX/site/._Gravies.md", "skipped_not_markdown"),
        ("site/logo.png", "skipped_not_markdown"),
        ("site/notes.txt", "skipped_not_markdown"),
    ]
    gravy = report.members[1]
    assert (gravy.url, gravy.title, gravy.published_on) == (
        "https://www.example.org/Products/Gravies",
        "Synthetic Pantry - Gravies and Au Jus",
        None,  # markdown.new emits no date, and the crawl date is never one
    )
    [page, *_] = list(pages(UPLOADS / "markdown-new.zip", host=HOST))
    # The comment and the block (with its nested meta mapping) are gone; the body is
    # taken as supplied, navigation and footer included (D11).
    assert not page.markdown.startswith(("<!--", "---"))
    assert "Synthetic description" not in page.markdown and "keywords" not in page.markdown
    assert page.markdown.startswith("[](https://www.example.org/)")
    assert "Buy now" in page.markdown


def test_the_front_matter_parser_reads_only_what_it_needs() -> None:
    url = "https://www.example.org/a?utm_source=x&id=3#top"
    page = parse_page(
        f"﻿<!-- Source: {url} -->\n\n---\ntitle: 'It''s \"quoted\"'\ndate: 2026-03-14\n"
        'meta:\n  description: "x: y"\n  keywords: [a, b]\nimage: |\n  multi\n  line\n'
        "tags:\n- one\n- two\nlayout: page # a comment\n---\n\n# Heading\n\nBody text.\n",
        HOST,
    )
    assert page == Page(
        "https://www.example.org/a?id=3",
        'It\'s "quoted"',
        date(2026, 3, 14),
        "# Heading\n\nBody text.",
    )
    # The url key alone is enough, and must agree with the comment when both are there.
    assert parse_page(f"---\nurl: {url}\n---\nBody\n", HOST).url == page.url
    assert parse_page(f"<!-- Source: {url} -->\n---\nurl: {url}\n---\nB\n", HOST).url == page.url
    # A comment with no block: the title from the first heading, then from the path.
    assert parse_page(f"<!-- Source: {url} -->\n# First\nBody\n", HOST).title == "First"
    assert parse_page(f"<!-- Source: {url} -->\nBody\n", HOST).title == "/a"
    titled = parse_page(f'---\nurl: {url}\ntitle: "{"x" * 600}\\u00e9"\n---\nB\n', HOST)
    assert len(titled.title) == 500
    for text, code in (
        ("Body only\n", "url_missing"),
        ("---\ntitle: x\n---\nBody\n", "url_missing"),
        (f"---\nurl: {url}\ntitle: |\n  folded\n---\nB\n", "front_matter_invalid"),
        (f"---\nurl: {url}\ntitle: [a]\n---\nB\n", "front_matter_invalid"),
        (f"---\nurl: {url}\ntitle: a\ntitle: b\n---\nB\n", "front_matter_invalid"),
        (f"---\nurl: {url}\n  stray indent\n---\nB\n", "front_matter_invalid"),
        (f"---\nurl: {url}\nTitle: x\n---\nB\n", "front_matter_invalid"),
        (f"---\nurl: {url}\ndate: 2026-02-30\n---\nB\n", "bad_date"),
        (f"---\nurl: {url}\ndate: 2026-03-14T10:00:00Z\n---\nB\n", "bad_date"),
        ("<!-- Source: ftp://www.example.org/a -->\nB\n", "bad_url"),
        ("<!-- Source: /relative/path -->\nB\n", "bad_url"),
        ("<!-- Source: https://sub.www.example.org/a -->\nB\n", "off_site"),
        (f"<!-- Source: {url} -->\n---\nurl: https://www.example.org/b\n---\nB\n", "url_mismatch"),
        (f"<!-- Source: {url} -->\n---\ntitle: x\n", "front_matter_invalid"),
        (f"<!-- Source: {url} -->\n---\ntitle: x\n---\n\n  \n", "empty"),
    ):
        with pytest.raises(_MemberRefused) as refused:
            parse_page(text, HOST)
        assert refused.value.code == code, text


def test_the_member_cap_holds_on_the_stream_whatever_the_zip_declares() -> None:
    """A ZIP that declares a small uncompressed size for a large member is never read
    past the cap: it fails its own check before anything is accepted from it."""
    body = b"<!-- Source: https://www.example.org/big -->\n" + b"a" * (6 * 1024 * 1024)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("site/first.md", b"<!-- Source: https://www.example.org/x -->\nBody\n")
        archive.writestr("big.md", body)
    raw = bytearray(buffer.getvalue())
    # Rewrite big.md's declared uncompressed size (central directory, offset 24) to 100.
    position = raw.find(b"PK\x01\x02", raw.find(b"PK\x01\x02") + 4)
    raw[position + 24 : position + 28] = (100).to_bytes(4, "little")
    with pytest.raises(UploadRefused) as refused:
        inspect_zip(bytes(raw), host=HOST)
    assert (refused.value.code, refused.value.member) == ("not_a_zip", 1)
    # The honest version of the same member is refused alone for its size.
    report = inspect_zip(buffer.getvalue(), host=HOST)
    assert [m.outcome for m in report.members] == ["accepted", "member_too_large"]


def test_the_total_and_member_count_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.content import uploads

    monkeypatch.setattr(uploads, "MAX_MEMBERS", 2)
    with pytest.raises(UploadRefused) as refused:
        inspect_zip(UPLOADS / "markdown-new.zip", host=HOST)
    assert (refused.value.code, refused.value.member) == ("too_many_members", 3)
    monkeypatch.setattr(uploads, "MAX_MEMBERS", 2000)
    monkeypatch.setattr(uploads, "MAX_TOTAL_BYTES", 600)
    with pytest.raises(UploadRefused) as refused:
        inspect_zip(UPLOADS / "markdown-new.zip", host=HOST)
    assert refused.value.code == "total_too_large"
    monkeypatch.setattr(uploads, "MAX_TOTAL_BYTES", 500 * 1024 * 1024)
    monkeypatch.setattr(uploads, "MAX_ENTRIES", 5)
    with pytest.raises(UploadRefused, match="too_many_members"):
        inspect_zip(UPLOADS / "markdown-new.zip", host=HOST)


def test_accepted_members_the_import_will_block_are_noted() -> None:
    report = inspect_zip(UPLOADS / "special-category.zip", host=HOST, special=special_for(None))
    health = report.members[1]
    assert (health.outcome, health.note, health.special_category) == (
        "accepted",
        "special_category",
        "health",
    )
    scoped = inspect_zip(UPLOADS / "markdown-new.zip", host=HOST, scope=Scope(("/Products/*",), ()))
    assert [m.note for m in scoped.members if m.outcome == "accepted"] == [
        None,
        None,
        "out_of_scope",
    ]


def test_the_committed_fixtures_are_what_the_script_builds(tmp_path: Path) -> None:
    script = UPLOADS / "make_uploads.py"
    spec = importlib.util.spec_from_file_location("make_uploads", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = tmp_path
    module.main()

    def contents(path: Path) -> list[tuple[str, int, bytes]]:
        if not zipfile.is_zipfile(path):
            return [("", 0, path.read_bytes())]
        with zipfile.ZipFile(path) as archive:
            return [
                (i.filename, 1, b"") if i.flag_bits & 1 else (i.filename, 0, archive.read(i))
                for i in archive.infolist()
            ]

    built = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert built == sorted(p.name for p in UPLOADS.glob("*.zip"))
    for name in built:
        assert contents(tmp_path / name) == contents(UPLOADS / name), name


# --- P2SR01-03 release and the import job -------------------------------------------------

UPLOAD_PUBLIC = PUBLIC | {
    "www.example.org": ["93.184.215.14"],
    "mirror.example.org": ["93.184.215.15"],
}
UPLOAD_START = "https://www.example.org/"
CRAWLED_ON = date(2026, 10, 30)
MIDNIGHT = datetime(2026, 10, 30, tzinfo=UTC)


def zip_of(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def members_of(name: str) -> dict[str, str]:
    with zipfile.ZipFile(UPLOADS / name) as archive:
        return {
            i.filename: archive.read(i).decode()
            for i in archive.infolist()
            if i.filename.endswith((".md", ".markdown"))
        }


class Up:
    """Uploads as the console makes them, released and imported as the worker does."""

    def __init__(self, c: Crawls) -> None:
        self.c = c
        self.e = c.e

    async def stage(
        self,
        content: bytes | str,
        *,
        site_id: UUID | None = None,
        mode: str = "partial",
        crawled_on: date = CRAWLED_ON,
        uploader: UUID | str | None = "editor",
        **spec: Any,
    ) -> StagedUpload:
        data = (UPLOADS / content).read_bytes() if isinstance(content, str) else content
        fields: dict[str, Any] = {
            "start_url": UPLOAD_START,
            "name": "Synthetic Pantry",
            "publisher": "Synthetic Pantry Co",
            "licence_basis": "publisher-terms",
            "tags": ("sample-web",),
            "origin": "upload",
        }
        return await stage_upload(
            self.e.factory,
            TAGS,
            data,
            content_root=self.e.content_root,
            uploader_id=self.e.user_id if uploader == "editor" else uploader,  # type: ignore[arg-type]
            crawled_on=crawled_on,
            mode=mode,
            declared=True,
            site_id=site_id,
            spec=None if site_id else SiteSpec(**(fields | spec)),
            resolve=resolver(UPLOAD_PUBLIC),
        )

    async def release(self, staged: StagedUpload) -> UUID:
        return await release_upload(
            self.e.factory, staged.site_id, staged.upload_id, self.e.user_id
        )

    async def imported(self, content: bytes | str, **kwargs: Any) -> StagedUpload:
        staged = await self.stage(content, **kwargs)
        await self.release(staged)
        await self.c.run()
        return staged

    async def row(self, staged: StagedUpload) -> asyncpg.Record:
        row = await self.c.admin.fetchrow(
            "SELECT * FROM site_uploads WHERE id = $1", staged.upload_id
        )
        assert row is not None
        return row


@pytest.fixture
def up(crawls: Crawls) -> Up:
    return Up(crawls)


async def test_a_released_upload_becomes_ingested_pages_of_the_site(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.stage("markdown-new-without-soup.zip")
    site_id = staged.site_id
    job_id = await up.release(staged)
    # The release approved the proposed site, recorded the declaration and queued the
    # import with the upload's ID only: no ZIP bytes, names or URLs in the payload.
    site = await up.c.site_row(site_id)
    assert (site["status"], site["approved_by"], site["allow_decision"]) == (
        "approved",
        up.e.user_id,
        "declared",
    )
    assert site["allow_checked_at"] is not None and site["next_crawl_at"] is None
    job = await admin_conn.fetchrow("SELECT type, payload FROM jobs WHERE id = $1", job_id)
    assert (job["type"], json.loads(job["payload"])) == (
        "import_crawl",
        {"upload_id": str(staged.upload_id)},
    )
    assert (await up.row(staged))["status"] == "queued"
    assert [e["after"] for e in await up.c.events("site.approved", site_id)] == [
        {"status": "approved"}
    ]
    await up.c.run()

    rows = await up.c.sources(site_id)
    gravies = "https://www.example.org/Products/Gravies"
    broth = "https://www.example.org/Products/Broth"
    assert set(rows) == {gravies, broth}
    for row in rows.values():
        assert (row["status"], row["type"], row["approved_by"], row["proposed_by"]) == (
            "ingested",
            "markdown",
            up.e.user_id,
            up.e.user_id,
        )
        assert (row["fetched_at"], row["snapshot_path"], row["published_on"]) == (
            MIDNIGHT,
            None,
            None,
        )
        assert row["site_id"] == site_id and row["tags"] == ["sample-web"]
    assert rows[gravies]["title"] == "Synthetic Pantry - Gravies and Au Jus"
    pages_ = await up.c.pages(site_id)
    assert {u: (p["state"], p["fetched_at"]) for u, p in pages_.items()} == {
        gravies: ("live", MIDNIGHT),
        broth: ("live", MIDNIGHT),
    }
    # Two ingestions; RAGFlow got the body without the Source comment or the block.
    ingestions = await admin_conn.fetchval(
        "SELECT count(*) FROM jobs WHERE type = 'ingest_source' AND status = 'succeeded'"
    )
    assert ingestions == 2
    sent = [content.decode() for _, _, content in up.e.fake.uploads]
    assert len(sent) == 2
    for body in sent:
        assert body.startswith("[](https://www.example.org/)")
        assert "<!-- Source" not in body and "meta:" not in body and "keywords" not in body
    # The upload, the site's crawl record and the audit trail.
    row = await up.row(staged)
    assert (row["status"], row["new_count"], row["staged_path"]) == ("imported", 2, None)
    assert row["imported_at"] is not None
    assert not (up.e.content_root / "uploads" / f"{row['zip_sha256']}.zip").exists()
    site = await up.c.site_row(site_id)
    assert (site["last_crawl_status"], site["page_count"], site["next_crawl_at"]) == (
        "imported",
        2,
        None,
    )
    [imported] = await up.c.events("site.upload_imported", site_id)
    assert (imported["new"], imported["changed"], imported["withdrawn"]) == (2, 0, 0)
    approvals = await admin_conn.fetch(
        "SELECT metadata FROM audit_events WHERE event = 'source.approved' "
        "AND metadata->>'site_id' = $1",
        str(site_id),
    )
    assert {json.loads(a["metadata"])["method"] for a in approvals} == {"crawl_upload"}
    [released] = await up.c.events("site.upload_released", site_id)
    assert (released["actor"], released["status"], released["self_approval"]) == (
        up.e.user_id,
        "site_approved",
        True,
    )


async def test_the_publication_date_comes_from_the_front_matter_only(up: Up) -> None:
    staged = await up.imported("dated.zip")
    rows = await up.c.sources(staged.site_id)
    assert rows["https://www.example.org/Dated"]["published_on"] == date(2026, 3, 14)
    assert rows["https://www.example.org/Products/Gravies"]["published_on"] is None


async def test_only_a_reviewer_releases_and_never_onto_a_withdrawn_site(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.stage("markdown-new.zip")
    await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError):
        await up.release(staged)
    with pytest.raises(RoleError):
        await reject_upload(
            up.e.factory,
            staged.site_id,
            staged.upload_id,
            up.e.user_id,
            note="no",
            content_root=up.e.content_root,
        )
    await content_user(admin_conn, "content_editor", "content_reviewer")
    with pytest.raises(RegisterError, match="no_upload"):
        await release_upload(up.e.factory, staged.site_id, uuid.uuid4(), up.e.user_id)
    await admin_conn.execute(
        "UPDATE sites SET status = 'withdrawn', withdrawn_at = now(), "
        "withdrawal_reason = 'r', approved_at = now() WHERE id = $1",
        staged.site_id,
    )
    with pytest.raises(RegisterError, match="site_withdrawn"):
        await up.release(staged)
    assert (await up.row(staged))["status"] == "staged"
    assert await admin_conn.fetchval("SELECT count(*) FROM jobs") == 0


async def test_a_rejected_upload_needs_a_note_and_leaves_nothing_behind(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.stage("markdown-new.zip")
    reject = {
        "factory": up.e.factory,
        "site_id": staged.site_id,
        "upload_id": staged.upload_id,
        "reviewer_id": up.e.user_id,
        "content_root": up.e.content_root,
    }
    with pytest.raises(RegisterError, match="note_required"):
        await reject_upload(**reject, note=" ")
    path = up.e.content_root / (await up.row(staged))["staged_path"]
    assert path.exists()
    await reject_upload(**reject, note="placeholder pages included")
    row = await up.row(staged)
    assert (row["status"], row["review_note"], row["staged_path"]) == (
        "rejected",
        "placeholder pages included",
        None,
    )
    assert not path.exists()
    with pytest.raises(RegisterError, match="not_staged"):
        await up.release(staged)
    site = await up.c.site_row(staged.site_id)
    assert site["status"] == "proposed"  # the site waits for a next upload
    [event] = await up.c.events("site.upload_rejected", staged.site_id)
    assert "placeholder" not in json.dumps(event, default=str)
    # A next upload for the site is accepted now that none is pending.
    again = await up.stage("markdown-new.zip", site_id=staged.site_id)
    assert again.site_id == staged.site_id


async def test_a_special_category_member_is_blocked_until_whitelisted(up: Up) -> None:
    staged = await up.imported("special-category.zip")
    site_id = staged.site_id
    health = "https://www.example.org/health/clinic"
    page = (await up.c.pages(site_id))[health]
    assert (page["state"], page["reason"], page["special_category"]) == (
        "blocked",
        "special_category",
        "health",
    )
    assert health not in await up.c.sources(site_id)
    assert (await up.row(staged))["blocked_count"] == 1
    await set_special_category_allow(up.e.factory, site_id, up.e.user_id, ["/health/*"])
    again = await up.imported("special-category.zip", site_id=site_id)
    assert (await up.c.pages(site_id))[health]["state"] == "live"
    assert (await up.row(again))["new_count"] == 1


async def test_a_member_with_another_sources_content_is_a_duplicate(up: Up) -> None:
    first = await up.imported("markdown-new.zip")
    # The same pages under another host: the same bodies, another site.
    # The same pages under another host: only the Source comment differs, so the
    # bodies (navigation included) are the same bytes.
    copy = {
        n: t.replace(
            "<!-- Source: https://www.example.org", "<!-- Source: https://mirror.example.org"
        )
        for n, t in members_of("markdown-new.zip").items()
    }
    staged = await up.stage(
        zip_of(copy),
        start_url="https://mirror.example.org/",
        name="Mirror",
    )
    await up.release(staged)
    await up.c.run()
    pages_ = await up.c.pages(staged.site_id)
    reasons = {p["reason"] for p in pages_.values()}
    assert reasons == {"duplicate_content"}, reasons
    assert len(await up.c.sources(first.site_id)) == 3


async def test_a_member_at_a_url_with_a_takedown_is_blocked(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.imported("markdown-new.zip")
    site_id = staged.site_id
    gravies = "https://www.example.org/Products/Gravies"
    row = (await up.c.sources(site_id))[gravies]
    await record_takedown(
        up.e.factory,
        row["id"],
        up.e.user_id,
        reference="TD-UP-1",
        requested_on=date(2026, 10, 30),
        licence_breach=False,
        licence_grounds=True,
    )
    await request_withdrawal(up.e.factory, row["id"], up.e.user_id, reason="takedown")
    await up.c.run()
    changed = members_of("markdown-new.zip")
    changed["site/Products/Gravies.md"] = changed["site/Products/Gravies.md"].replace(
        "six hours", "seven hours"
    )
    again = await up.imported(zip_of(changed), site_id=site_id)
    page = (await up.c.pages(site_id))[gravies]
    assert page["state"] == "blocked" and page["reason"] in ("taken_down", "withdrawn")
    assert gravies not in await up.c.sources(site_id)
    assert (await up.row(again))["new_count"] == 0


async def test_a_paused_pages_new_version_is_ingested_paused(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.imported("markdown-new.zip")
    site_id = staged.site_id
    gravies = "https://www.example.org/Products/Gravies"
    old = (await up.c.sources(site_id))[gravies]
    await pause(up.e.factory, up.e.fake, old["id"], up.e.user_id, reason=REASON)  # type: ignore[arg-type]
    again = await up.imported("markdown-new-second.zip", site_id=site_id)
    new = await admin_conn.fetchrow("SELECT * FROM sources WHERE supersedes_id = $1", old["id"])
    assert (new["status"], new["pause_reason"]) == ("paused", REASON)
    assert (await source_row(admin_conn, old["id"]))["status"] == "withdrawn"
    assert (await up.row(again))["changed_count"] == 1


async def test_an_import_whose_zip_is_gone_or_altered_fails_and_changes_nothing(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.stage("markdown-new.zip")
    await up.release(staged)
    path = up.e.content_root / (await up.row(staged))["staged_path"]
    path.write_bytes(b"altered")
    await up.c.run()
    row = await up.row(staged)
    assert (row["status"], row["error"]) == ("failed", "upload_altered")
    assert await up.c.sources(staged.site_id) == {}
    assert await up.c.pages(staged.site_id) == {}
    [failed] = await up.c.events("site.upload_failed", staged.site_id)
    assert failed["error_code"] == "upload_altered"
    job = await admin_conn.fetchrow(
        "SELECT status, error_code FROM jobs WHERE type = 'import_crawl'"
    )
    assert tuple(job) == ("failed", "upload_altered")
    # A failed upload is no longer pending: the editor may upload again.
    again = await up.stage("markdown-new.zip", site_id=staged.site_id)
    path.unlink()
    await up.release(again)
    await up.c.run()
    assert (await up.row(again))["error"] == "upload_missing"


# --- P2SR01-04 second upload: supersession, full and partial -------------------------------

GRAVIES = "https://www.example.org/Products/Gravies"
BROTH = "https://www.example.org/Products/Broth"
SOUP = "https://www.example.org/Recipes/Soup"
STOCK = "https://www.example.org/Products/Stock"


async def test_a_partial_second_upload_supersedes_adds_and_keeps_the_rest(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    first = await up.imported("markdown-new.zip")
    site_id = first.site_id
    old = await up.c.sources(site_id)
    citation = await cite(admin_conn, INTERNAL_TENANT_ID, up.e.user_id, old[GRAVIES]["id"])
    parsed = len(up.e.fake.parsed)
    # Gravies changed, Broth's front matter only (unchanged), Stock new, Soup absent.
    second = await up.imported(
        "markdown-new-second.zip", site_id=site_id, crawled_on=date(2026, 10, 31)
    )
    row = await up.row(second)
    counts = {k: row[f"{k}_count"] for k in ("new", "changed", "unchanged", "blocked")}
    assert counts == {"new": 1, "changed": 1, "unchanged": 1, "blocked": 0}
    assert row["withdrawn_count"] == 0
    now = await up.c.sources(site_id)
    assert set(now) == {GRAVIES, BROTH, SOUP, STOCK}  # partial: Soup kept
    assert now[GRAVIES]["supersedes_id"] == old[GRAVIES]["id"]
    assert (await source_row(admin_conn, old[GRAVIES]["id"]))["status"] == "withdrawn"
    assert await flags(admin_conn, citation) == (True, False)  # labelled superseded
    # The unchanged page is the same row, not re-ingested; its fetch date moved on.
    assert now[BROTH]["id"] == old[BROTH]["id"]
    assert len(up.e.fake.parsed) == parsed + 2  # Gravies v2 and Stock only
    pages_ = await up.c.pages(site_id)
    assert pages_[BROTH]["fetched_at"] == datetime(2026, 10, 31, tzinfo=UTC)
    assert pages_[SOUP]["fetched_at"] == MIDNIGHT  # untouched
    assert (await up.c.site_row(site_id))["page_count"] == 4


async def test_a_full_upload_withdraws_the_absent_pages_and_says_how_many_first(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    first = await up.imported("markdown-new.zip")
    site_id = first.site_id
    soup = (await up.c.sources(site_id))[SOUP]
    citation = await cite(admin_conn, INTERNAL_TENANT_ID, up.e.user_id, soup["id"])
    staged = await up.stage("markdown-new-without-soup.zip", site_id=site_id, mode="full")
    assert staged.would_withdraw == 1
    pending = await upload_report(
        up.e.factory, site_id, staged.upload_id, content_root=up.e.content_root
    )
    assert pending.would_withdraw == 1  # what the reviewer sees on the release button
    await up.release(staged)
    await up.c.run()
    row = await up.row(staged)
    assert (row["withdrawn_count"], row["unchanged_count"]) == (1, 2)
    page = (await up.c.pages(site_id))[SOUP]
    assert (page["state"], page["reason"]) == ("removed", "not_in_upload")
    gone = await source_row(admin_conn, soup["id"])
    assert (gone["status"], gone["withdrawal_reason"]) == (
        "withdrawn",
        "page absent from a full upload of the site's crawl",
    )
    assert await flags(admin_conn, citation) == (False, True)
    requested = await up.c.events("source.withdrawal_requested", site_id)
    assert [(r["source_id"], r["method"]) for r in requested] == [(str(soup["id"]), "crawl_upload")]
    assert set(await up.c.sources(site_id)) == {GRAVIES, BROTH}
    assert (await up.c.site_row(site_id))["page_count"] == 2


async def test_the_same_zip_as_a_partial_upload_withdraws_nothing(up: Up) -> None:
    first = await up.imported("markdown-new.zip")
    staged = await up.stage("markdown-new-without-soup.zip", site_id=first.site_id)
    assert staged.would_withdraw is None
    await up.release(staged)
    await up.c.run()
    assert (await up.row(staged))["withdrawn_count"] == 0
    assert set(await up.c.sources(first.site_id)) == {GRAVIES, BROTH, SOUP}


async def test_a_full_upload_treats_held_pages_as_the_crawler_does(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    """A page under a takedown is never given a new version (the crawler's ``_held``
    rule), and one absent from a full upload is withdrawn as a crawl withdraws a page
    that is gone: the takedown's own withdrawal is not delayed or duplicated."""
    first = await up.imported("markdown-new.zip")
    site_id = first.site_id
    rows = await up.c.sources(site_id)
    for url, reference in ((GRAVIES, "TD-UP-2"), (SOUP, "TD-UP-3")):
        await record_takedown(
            up.e.factory,
            rows[url]["id"],
            up.e.user_id,
            reference=reference,
            requested_on=date(2026, 10, 30),
            licence_breach=False,
            licence_grounds=False,
        )
    changed = members_of("markdown-new-without-soup.zip")
    changed["site/Products/Gravies.md"] = changed["site/Products/Gravies.md"].replace(
        "six hours", "nine hours"
    )
    staged = await up.stage(zip_of(changed), site_id=site_id, mode="full")
    assert staged.would_withdraw == 1
    await up.release(staged)
    await up.c.run()
    now = await up.c.sources(site_id)
    assert now[GRAVIES]["id"] == rows[GRAVIES]["id"]  # no new version past the takedown
    assert now[GRAVIES]["takedown_reference"] == "TD-UP-2"
    soup = await source_row(admin_conn, rows[SOUP]["id"])
    assert (soup["status"], soup["takedown_reference"]) == ("withdrawn", "TD-UP-3")
    assert (await up.row(staged))["withdrawn_count"] == 1


async def test_an_upload_site_never_gets_a_next_crawl(up: Up) -> None:
    staged = await up.imported("markdown-new.zip")
    await up.imported("markdown-new-second.zip", site_id=staged.site_id, mode="full")
    site = await up.c.site_row(staged.site_id)
    assert (site["schedule"], site["next_crawl_at"], site["last_crawl_status"]) == (
        "none",
        None,
        "imported",
    )
    assert await schedule_due_crawls(up.e.factory) == 0


# --- P2SR01-05 the CLI --------------------------------------------------------------------


def test_cli_upload_crawl_flags() -> None:
    args = cli.build_parser().parse_args(
        [
            "sites",
            "upload-crawl",
            "crawl.zip",
            "--start-url",
            UPLOAD_START,
            "--name",
            "n",
            "--publisher",
            "p",
            "--licence-basis",
            "l",
            "--tag",
            "sample-web",
            "--crawled-on",
            "2026-10-30",
            "--full",
            "--declare-robots-honoured",
            "--approve-as",
            "r@example.org",
            "--wait",
        ]
    )
    assert (args.full, args.partial, args.crawled_on, args.tag) == (
        True,
        False,
        CRAWLED_ON,
        ["sample-web"],
    )
    with pytest.raises(SystemExit):  # --full and --partial together
        cli.build_parser().parse_args(
            ["sites", "upload-crawl", "z", "--crawled-on", "2026-10-30", "--full", "--partial"]
        )
    with pytest.raises(SystemExit):  # the crawl date is required
        cli.build_parser().parse_args(["sites", "upload-crawl", "z"])
    with pytest.raises(SystemExit, match="--site or the new site"):
        cli.main(
            [
                "sites",
                "upload-crawl",
                "z",
                "--site",
                str(uuid.uuid4()),
                "--name",
                "n",
                "--crawled-on",
                "2026-10-30",
            ]
        )


async def test_cli_upload_crawl_goes_through_the_same_path(
    up: Up,
    database: MigratedDatabase,
    admin_conn: asyncpg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    settings = load_settings(environ=ENV)
    secrets = replace(settings.secrets, database_url=SecretStr(database.sqlalchemy_url))
    files = settings.models.files.model_copy(update={"content_root": up.e.content_root})
    settings = replace(
        settings, secrets=secrets, models=settings.models.model_copy(update={"files": files})
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    terminal = tmp_path / "tty"
    monkeypatch.setattr(cli, "TERMINAL", str(terminal))
    first = await up.imported("markdown-new.zip")
    site = str(first.site_id)

    def parsed(*argv: str) -> Any:
        return cli.build_parser().parse_args(["sites", "upload-crawl", *argv])

    zip_path = str(UPLOADS / "markdown-new-second.zip")
    base = (zip_path, "--site", site, "--crawled-on", "2026-10-31")
    # Without the declaration nothing runs, and the sentence is shown.
    with pytest.raises(SystemExit) as refused:
        await cli._upload_crawl(parsed(*base))
    assert "I confirm that this crawl of www.example.org was made on 2026-10-31" in str(
        refused.value
    )
    assert await admin_conn.fetchval("SELECT count(*) FROM site_uploads") == 1
    # A new site needs its fields.
    with pytest.raises(SystemExit, match="needs --start-url"):
        await cli._upload_crawl(parsed(zip_path, "--crawled-on", "2026-10-31"))
    # An editor-less reviewer cannot be the uploader.
    await content_user(admin_conn, "content_reviewer")
    with pytest.raises(SystemExit, match="not_content_editor"):
        await cli._upload_crawl(
            parsed(*base, "--declare-robots-honoured", "--approve-as", "editor@example.org")
        )
    await content_user(admin_conn, "content_editor", "content_reviewer")
    # Staged only, then released in the same run.
    assert await cli._upload_crawl(parsed(*base, "--declare-robots-honoured", "--full")) == 0
    row = await admin_conn.fetchrow(
        "SELECT * FROM site_uploads WHERE status = 'staged' AND site_id = $1", first.site_id
    )
    assert (row["mode"], row["uploaded_by"]) == ("full", None)
    shown = terminal.read_text()
    assert "site/Products/Stock.md" in shown and "Declared: I confirm" in shown
    assert "1 live page(s) absent from the ZIP will be withdrawn" in shown
    logged = capsys.readouterr().out
    no_names = ("Stock", "Gravies", "site/", "/Products")
    assert not [n for n in no_names if n in logged]
    assert '"event":"sites.upload_crawl"' in logged
    with pytest.raises(SystemExit, match="upload_pending"):
        await cli._upload_crawl(parsed(*base, "--declare-robots-honoured"))
    await reject_upload(
        up.e.factory,
        first.site_id,
        row["id"],
        up.e.user_id,
        note="n",
        content_root=up.e.content_root,
    )
    reviewer = ("--approve-as", "editor@example.org")
    assert await cli._upload_crawl(parsed(*base, "--declare-robots-honoured", *reviewer)) == 0
    await up.c.run()
    released = await admin_conn.fetchrow(
        "SELECT * FROM site_uploads WHERE site_id = $1 ORDER BY uploaded_at DESC LIMIT 1",
        first.site_id,
    )
    assert (released["status"], released["changed_count"], released["new_count"]) == (
        "imported",
        1,
        1,
    )
    assert released["uploaded_by"] == released["released_by"] == up.e.user_id
    # Whole-upload refusals exit with the code and the member index, never its name.
    with pytest.raises(SystemExit) as dup:
        await cli._upload_crawl(
            parsed(
                str(UPLOADS / "duplicate-url.zip"),
                "--site",
                site,
                "--crawled-on",
                "2026-10-31",
                "--declare-robots-honoured",
            )
        )
    assert str(dup.value) == "ask-spore sites upload-crawl: duplicate_url (member 1)"
    # Without a terminal the report is not shown anywhere, and the log says so.
    monkeypatch.setattr(cli, "TERMINAL", str(tmp_path / "missing" / "tty"))
    await cli._upload_crawl(
        parsed(
            str(UPLOADS / "dated.zip"),
            "--site",
            site,
            "--crawled-on",
            "2026-10-31",
            "--declare-robots-honoured",
        )
    )
    logged = capsys.readouterr().out
    assert "report_not_shown_no_terminal" in logged and "Dated" not in logged


# --- P2SR01-05 the tenant-facing path (no new code) ---------------------------------------


async def test_an_uploaded_site_reaches_tenants_exactly_as_a_crawled_one(
    up: Up, admin_conn: asyncpg.Connection
) -> None:
    staged = await up.imported("markdown-new.zip")
    rows = await up.c.sources(staged.site_id)
    web = await web_tenant(admin_conn)  # its workspace holds sample-web
    reports, _ = await other_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-reports'] WHERE tenant_id = $1", reports
    )

    async def listed(tenant_id: UUID) -> tuple[list[Any], list[Any], UUID]:
        async with tenant_session(up.e.factory, tenant_id) as session:
            workspace = await session.scalar(sql("SELECT id FROM workspaces LIMIT 1"))
            files, sites = await workspace_files(session, workspace)
        return files, sites, workspace

    files, sites, workspace = await listed(web)
    assert files == []  # pages are never files
    assert [(s.site, s.publisher, s.page_count) for s in sites] == [
        ("www.example.org", "Synthetic Pantry Co", 3)
    ]
    assert (await listed(reports))[1] == []  # a workspace without the tag sees nothing
    # A page is never downloadable: refused as for a file outside the workspace.
    async with tenant_session(up.e.factory, web) as session:
        with pytest.raises(FileRefused, match="not_found"):
            await issue_link(
                session,
                tenant_id=web,
                ttl_seconds=60,
                workspace_id=workspace,
                user_id=up.e.user_id,
                source_id=rows[GRAVIES]["id"],
                daily_cap=10,
            )
    # Cited with the page URL as the canonical link ("View at source"), the site's
    # publisher and the page's title, as a crawled page is.
    documents = [d for r in rows.values() for d in json.loads(r["ragflow_document_ids"]).values()]
    async with tenant_session(up.e.factory, web) as session:
        provenance = await provenance_by_document(session, documents)
    by_url = {p.canonical_url: p for p in provenance.values()}
    assert set(by_url) == {GRAVIES, BROTH, SOUP}
    assert (by_url[GRAVIES].title, by_url[GRAVIES].publisher, by_url[GRAVIES].type) == (
        "Synthetic Pantry - Gravies and Au Jus",
        "Synthetic Pantry Co",
        "markdown",
    )
    assert by_url[GRAVIES].untrusted  # crawled text is wrapped as untrusted, so is this
    # Retrieval through each tenant's own package: the pages for one, nothing for the other.
    for tenant_id, expected in ((web, 3), (reports, 0)):
        async with tenant_session(up.e.factory, tenant_id) as session:
            workspace_id = await session.scalar(sql("SELECT id FROM workspaces LIMIT 1"))
            package = await workspace_package(session, workspace_id)
        chunks = await up.e.fake.retrieve_chunks(
            dataset_ids=package.dataset_ids, question="q", top_k=100, similarity_threshold=0.2
        )
        assert len({c.document_id for c in chunks if c.document_id in documents}) == expected


async def test_an_import_that_crashes_fails_the_upload_instead_of_blocking_the_site(
    up: Up, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.content import uploadcrawl

    staged = await up.stage("markdown-new.zip")
    await up.release(staged)

    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(uploadcrawl._UploadImport, "sweep", boom)
    await up.c.run()
    row = await up.row(staged)
    assert (row["status"], row["error"]) == ("failed", "internal_error")
    monkeypatch.undo()
    again = await up.stage("markdown-new.zip", site_id=staged.site_id)
    assert again.site_id == staged.site_id  # the site takes its next upload
