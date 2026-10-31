"""P2SR01: uploaded crawls. Upload sites, the ZIP inspection, release and the
``import_crawl`` job, against PostgreSQL and a fake RAGFlow. Synthetic pages only
(``packages/eval/fixtures/uploads/``)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app.content.crawler import HostLimiter
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
