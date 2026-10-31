"""P2SR01: uploaded crawls. Upload sites, the ZIP inspection, release and the
``import_crawl`` job, against PostgreSQL and a fake RAGFlow. Synthetic pages only
(``packages/eval/fixtures/uploads/``)."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import uuid
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app.content.crawler import HostLimiter, Scope
from app.content.jobs import JOB_TYPES, PAYLOAD_KEYS, enqueue
from app.content.register import RegisterError
from app.content.sitecrawl import crawl_site
from app.content.sites import (
    SiteSettings,
    SiteSpec,
    approve_site,
    register_site,
    request_crawl,
    schedule_due_crawls,
    update_site,
)
from app.content.uploads import (
    Page,
    UploadRefused,
    _MemberRefused,
    inspect_zip,
    pages,
    parse_page,
    special_for,
)
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase, _admin_dsn, _execute, _with_database, migrate
from tests.test_crawler import ROOT, resolver
from tests.test_ingest import TAGS, env
from tests.test_sites import PUBLIC, Crawls, crawls

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
