"""P1b-04: crawl management. Sites, the crawl_site job and the register, against
PostgreSQL, a fake site (httpx.MockTransport), a fake RAGFlow and a fake clock.
Synthetic pages only."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app.content import worker
from app.content.crawler import HostLimiter
from app.content.fetch import FetchError
from app.content.register import RegisterError, record_takedown, request_withdrawal
from app.content.roles import RoleError
from app.content.sites import (
    SiteSettings,
    SiteSpec,
    approve_site,
    register_site,
    reject_site,
    request_crawl,
    schedule_due_crawls,
    set_special_category_allow,
    update_site,
)
from app.content.submit import settle, settle_site, submit_site
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fakes import FakeRedis
from tests.test_crawler import ROOT, Clock, Site, html, resolver
from tests.test_ingest import TAGS, Env, Ingest, content_user, env
from tests.test_withdraw import cite, flags

__all__ = ["env"]  # the fixture, imported for its use here

PUBLIC = {"site.example": ["93.184.216.34"]}
DATED = '<meta property="article:published_time" content="2026-02-10">'


def pages() -> dict[str, Any]:
    home = html("Home", "Welcome").replace(
        "</main>", "<a href='/a'>A</a><a href='/b'>B</a><a href='/health/clinic'>C</a></main>"
    )
    return {
        "/": home,
        "/a": html("Page A", "Alpha", DATED),
        "/b": html("Page B", "Beta published 2026-03-01"),  # a date in the text only
        "/health/clinic": html("Clinic opening hours", "Opening"),
    }


class Crawls:
    def __init__(self, e: Env, admin: asyncpg.Connection) -> None:
        self.e = e
        self.admin = admin
        self.site = Site(pages())
        self.clock = Clock()
        self.context = worker.Context(
            factory=e.factory,
            client=e.fake,  # type: ignore[arg-type]
            tags=TAGS,
            content_root=e.content_root,
            parse_poll_interval=0,
            http=self.site.client,
            limiter=HostLimiter(clock=lambda: self.clock.now, sleep=self.clock.sleep),
            resolve=resolver(PUBLIC),
        )

    async def register(self, **overrides: Any) -> UUID:
        fields: dict[str, Any] = {
            "start_url": ROOT + "/",
            "name": "Synthetic Energy Institute",
            "publisher": "Synthetic Energy Institute",
            "licence_basis": "publisher-terms",
            "tags": ("sample-web",),
        }
        spec = SiteSpec(**(fields | overrides))
        site_id, created = await register_site(
            self.e.factory, TAGS, spec, proposer_id=self.e.user_id, resolve=resolver(PUBLIC)
        )
        assert created
        return site_id

    async def approved(self, **overrides: Any) -> UUID:
        site_id = await self.register(**overrides)
        await approve_site(self.e.factory, site_id, self.e.user_id)
        return site_id

    async def run(self) -> None:
        """Run the queue to the end: crawls, their ingestions and withdrawals."""
        registry = worker.handlers(self.context)
        while await worker.run_once(self.e.factory, registry):
            pass

    async def crawl(self, site_id: UUID) -> None:
        await request_crawl(self.e.factory, site_id, self.e.user_id)
        await self.run()

    async def sources(self, site_id: UUID) -> dict[str, asyncpg.Record]:
        """The site's current register rows by page URL."""
        rows = await self.admin.fetch(
            "SELECT * FROM sources WHERE site_id = $1 ORDER BY created_at", site_id
        )
        return {r["canonical_url"]: r for r in rows if r["status"] != "withdrawn"}

    async def pages(self, site_id: UUID) -> dict[str, asyncpg.Record]:
        rows = await self.admin.fetch("SELECT * FROM site_pages WHERE site_id = $1", site_id)
        return {r["url"]: r for r in rows}

    async def site_row(self, site_id: UUID) -> asyncpg.Record:
        row = await self.admin.fetchrow("SELECT * FROM sites WHERE id = $1", site_id)
        assert row is not None
        return row

    async def events(self, name: str, site_id: UUID) -> list[dict[str, Any]]:
        rows = await self.admin.fetch(
            "SELECT actor_user_id, metadata FROM audit_events WHERE event = $1 "
            "AND metadata->>'site_id' = $2 ORDER BY created_at, id",
            name,
            str(site_id),
        )
        return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]


@pytest.fixture
async def crawls(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> AsyncIterator[Crawls]:
    e, _ = env
    yield Crawls(e, admin_conn)
    await admin_conn.execute("DELETE FROM conversations")


# --- registration and review --------------------------------------------------------------


async def test_a_site_is_proposed_by_an_editor_and_reaches_nothing_before_approval(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    site_id = await crawls.register(allow_patterns=("/", "/reports/*"), schedule="weekly")
    row = await crawls.site_row(site_id)
    assert (row["status"], row["host"], row["proposed_by"]) == (
        "proposed",
        "site.example",
        crawls.e.user_id,
    )
    assert (row["allow_patterns"], row["schedule"], row["allow_decision"]) == (
        ["/", "/reports/*"],
        "weekly",
        "unchecked",
    )
    assert await admin_conn.fetchval("SELECT count(*) FROM jobs") == 0
    await crawls.run()
    assert crawls.site.requested == []  # nothing fetched, nothing ingested
    with pytest.raises(RegisterError) as refused:
        await request_crawl(crawls.e.factory, site_id, crawls.e.user_id)
    assert refused.value.code == "not_approved"
    [event] = await crawls.events("site.proposed", site_id)
    assert (event["actor"], event["site_id"], event["after"]["status"]) == (
        crawls.e.user_id,
        str(site_id),
        "proposed",
    )
    assert "site.example" not in json.dumps(event, default=str)  # identifiers and settings only


async def test_registration_checks_roles_input_and_the_host(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    for overrides, code in (
        ({"allow_patterns": ("reports/*",)}, "bad_pattern"),
        ({"schedule": "daily"}, "bad_schedule"),
        ({"max_pages": 0}, "bad_max_pages"),
        ({"tags": ("no-such-tag",)}, "unknown_tag"),
        ({"name": " "}, "missing_metadata"),
    ):
        with pytest.raises(RegisterError) as refused:
            await crawls.register(**overrides)
        assert refused.value.code == code
    spec = SiteSpec(ROOT + "/", "N", "P", "publisher-terms", ("sample-web",))
    with pytest.raises(FetchError) as private:
        await register_site(
            e.factory,
            TAGS,
            spec,
            proposer_id=e.user_id,
            resolve=resolver({"site.example": ["10.0.0.2"]}),
        )
    assert private.value.code == "not_public"
    await content_user(admin_conn, "content_reviewer")
    with pytest.raises(RoleError):
        await crawls.register()
    assert await admin_conn.fetchval("SELECT count(*) FROM sites") == 0


async def test_an_editor_cannot_approve_and_a_rejection_needs_a_note(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.register()
    await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError):
        await approve_site(e.factory, site_id, e.user_id)
    with pytest.raises(RoleError):
        await update_site(e.factory, site_id, e.user_id, SiteSettings((), (), "none", 10))
    await content_user(admin_conn, "content_editor", "content_reviewer")
    with pytest.raises(RegisterError):
        await reject_site(e.factory, site_id, e.user_id, note=" ")
    await reject_site(e.factory, site_id, e.user_id, note="out of our remit")
    row = await crawls.site_row(site_id)
    assert (row["status"], row["review_note"]) == ("rejected", "out of our remit")
    [event] = await crawls.events("site.rejected", site_id)
    assert "remit" not in json.dumps(event, default=str)  # the note stays on the row


# --- the crawl ----------------------------------------------------------------------------


async def test_an_approved_site_is_crawled_and_each_page_becomes_a_register_row(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved(schedule="monthly")
    await crawls.run()

    sources = await crawls.sources(site_id)
    assert sorted(sources) == [ROOT + "/", ROOT + "/a", ROOT + "/b"]
    page_a = sources[ROOT + "/a"]
    assert (page_a["status"], page_a["type"], page_a["tags"]) == (
        "ingested",
        "markdown",
        ["sample-web"],
    )
    assert (page_a["title"], page_a["publisher"]) == ("Page A", "Synthetic Energy Institute")
    assert (page_a["proposed_by"], page_a["approved_by"]) == (e.user_id, e.user_id)
    assert page_a["published_on"] == date(2026, 2, 10)  # explicit metadata
    assert sources[ROOT + "/b"]["published_on"] is None  # never guessed from the text
    assert page_a["fetched_at"] is not None
    snapshot = e.content_root / page_a["snapshot_path"]
    assert snapshot.read_bytes().startswith(b"<html>")  # the raw HTML, for provenance
    staged = e.content_root / f"{page_a['file_sha256'][:2]}/{page_a['file_sha256']}.markdown"
    assert b"Alpha sentence 0" in staged.read_bytes()
    assert len(e.fake.uploads) == 3  # one dataset each

    site = await crawls.site_row(site_id)
    assert (site["allow_decision"], site["last_crawl_status"], site["page_count"]) == (
        "allowed",
        "ok",
        3,
    )
    assert site["next_crawl_at"] is not None and site["allow_checked_at"] is not None
    # Approved in the reviewer's name by the site's approval, audited as such.
    approvals = [x for x in await crawls.events("source.approved", site_id) if x.get("site_id")]
    assert len(approvals) == 3 and {x["method"] for x in approvals} == {"site_crawl"}
    [crawled] = await crawls.events("site.crawled", site_id)
    assert (crawled["outcome"], crawled["count"], crawled["status"]) == ("ok", 3, "allowed")
    assert "Alpha" not in json.dumps(await crawls.events("source.proposed", site_id))


async def test_a_special_category_page_is_skipped_listed_and_whitelisted_by_a_reviewer(
    crawls: Crawls,
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    clinic = (await crawls.pages(site_id))[ROOT + "/health/clinic"]
    assert (clinic["state"], clinic["reason"], clinic["special_category"]) == (
        "blocked",
        "special_category",
        "health",
    )
    assert clinic["source_id"] is None
    assert ROOT + "/health/clinic" not in await crawls.sources(site_id)

    await set_special_category_allow(e.factory, site_id, e.user_id, ["/health/*"])
    [event] = await crawls.events("site.special_category_allow_changed", site_id)
    assert (event["before"], event["after"]) == (
        {"special_category_allow": []},
        {"special_category_allow": ["/health/*"]},
    )
    await crawls.crawl(site_id)
    assert (await crawls.pages(site_id))[ROOT + "/health/clinic"]["state"] == "live"
    assert (await crawls.sources(site_id))[ROOT + "/health/clinic"]["status"] == "ingested"


async def test_an_unchanged_page_is_not_ingested_again(crawls: Crawls) -> None:
    site_id = await crawls.approved()
    await crawls.run()
    before = await crawls.sources(site_id)
    uploads = len(crawls.e.fake.uploads)
    await crawls.crawl(site_id)
    assert {u: r["id"] for u, r in (await crawls.sources(site_id)).items()} == {
        u: r["id"] for u, r in before.items()
    }
    assert len(crawls.e.fake.uploads) == uploads


async def test_a_changed_page_is_reingested_and_supersedes_the_old_version(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    old = (await crawls.sources(site_id))[ROOT + "/a"]
    citation = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, old["id"])

    crawls.site.pages["/a"] = html("Page A", "Alpha revised", DATED)
    await crawls.crawl(site_id)
    new = (await crawls.sources(site_id))[ROOT + "/a"]
    assert new["id"] != old["id"] and new["supersedes_id"] == old["id"]
    assert new["status"] == "ingested" and new["canonical_url"] == ROOT + "/a"
    old_row = await admin_conn.fetchrow("SELECT * FROM sources WHERE id = $1", old["id"])
    assert old_row["status"] == "withdrawn"
    assert not set(json.loads(old["ragflow_document_ids"]).values()) & set(e.fake.documents)
    assert await flags(admin_conn, citation) == (True, False)  # superseded
    page = (await crawls.pages(site_id))[ROOT + "/a"]
    assert (page["state"], page["source_id"]) == ("live", new["id"])


async def test_a_removed_page_is_withdrawn(crawls: Crawls, admin_conn: asyncpg.Connection) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    gone = (await crawls.sources(site_id))[ROOT + "/b"]
    citation = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, gone["id"])

    del crawls.site.pages["/b"]  # the link stays on the home page: a 404
    await crawls.crawl(site_id)
    page = (await crawls.pages(site_id))[ROOT + "/b"]
    assert (page["state"], page["reason"]) == ("removed", "http_404")
    row = await admin_conn.fetchrow("SELECT * FROM sources WHERE id = $1", gone["id"])
    assert (row["status"], row["withdrawal_reason"]) == (
        "withdrawn",
        "page removed from the site (HTTP 404)",
    )
    assert await flags(admin_conn, citation) == (False, True)
    assert not (e.content_root / gone["snapshot_path"]).exists()  # the snapshot goes too
    assert (await crawls.site_row(site_id))["page_count"] == 2

    # A page no longer linked from anywhere is checked directly; still there, it stays.
    crawls.site.pages["/"] = html("Home", "Welcome").replace("</main>", "<a href='/b'>B</a></main>")
    crawls.site.pages["/b"] = html("Page B", "Beta back")
    await crawls.crawl(site_id)
    live = {u for u, p in (await crawls.pages(site_id)).items() if p["state"] == "live"}
    assert live == {ROOT + "/", ROOT + "/a", ROOT + "/b"}  # /a revisited, not removed


async def test_scope_rules_are_enforced_and_a_narrower_scope_withdraws_pages(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved(deny_patterns=("/b",))
    await crawls.run()
    assert sorted(await crawls.sources(site_id)) == [ROOT + "/", ROOT + "/a"]
    assert "/b" not in crawls.site.requested

    await update_site(e.factory, site_id, e.user_id, SiteSettings(("/",), (), "none", 50))
    [event] = await crawls.events("site.settings_changed", site_id)
    assert (event["before"]["deny_patterns"], event["after"]["allow_patterns"]) == (["/b"], ["/"])
    await crawls.crawl(site_id)
    page = (await crawls.pages(site_id))[ROOT + "/a"]
    assert (page["state"], page["reason"]) == ("blocked", "out_of_scope")
    assert sorted(await crawls.sources(site_id)) == [ROOT + "/"]


async def test_robots_and_the_tdm_reservation_are_honoured_per_site(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    site_id = await crawls.approved()
    await crawls.run()
    assert len(await crawls.sources(site_id)) == 3

    crawls.site.pages["/.well-known/tdmrep.json"] = (
        200,
        {},
        json.dumps([{"location": "/*", "tdm-reservation": 1}]),
    )
    await crawls.crawl(site_id)
    site = await crawls.site_row(site_id)
    assert (site["allow_decision"], site["page_count"]) == ("tdm_reserved", 0)
    assert await crawls.sources(site_id) == {}  # every page withdrawn
    reasons = await admin_conn.fetch(
        "SELECT DISTINCT withdrawal_reason FROM sources WHERE site_id = $1", site_id
    )
    assert [r[0] for r in reasons] == ["the site reserves text-and-data-mining rights"]

    del crawls.site.pages["/.well-known/tdmrep.json"]
    crawls.site.pages["/robots.txt"] = (200, {}, "User-agent: *\nDisallow: /\n")
    requested = len(crawls.site.requested)
    await crawls.crawl(site_id)
    assert (await crawls.site_row(site_id))["allow_decision"] == "robots_disallowed"
    assert crawls.site.requested[requested:] == ["/robots.txt"]  # no page fetched


async def test_a_page_a_reviewer_withdrew_stays_out(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    page_a = (await crawls.sources(site_id))[ROOT + "/a"]
    await record_takedown(
        e.factory,
        page_a["id"],
        e.user_id,
        reference="TD-WEB-1",
        requested_on=date(2026, 10, 22),
        licence_breach=False,
    )
    await request_withdrawal(e.factory, page_a["id"], e.user_id, reason="takedown request")
    await crawls.run()
    crawls.site.pages["/a"] = html("Page A", "Alpha changed")  # even with new content
    await crawls.crawl(site_id)
    assert ROOT + "/a" not in await crawls.sources(site_id)
    page = (await crawls.pages(site_id))[ROOT + "/a"]
    assert (page["state"], page["reason"]) == ("blocked", "withdrawn")


async def test_a_crawl_needs_an_approver_who_is_still_a_reviewer(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    await crawls.approved()
    await content_user(admin_conn, "content_editor")
    await crawls.run()
    job = await admin_conn.fetchrow("SELECT status, error_code FROM jobs WHERE type = 'crawl_site'")
    assert (job["status"], job["error_code"]) == ("failed", "approver_lacks_role")
    assert crawls.site.requested == []


async def test_an_unreachable_site_keeps_its_pages(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    site_id = await crawls.approved()
    await crawls.run()
    crawls.site.pages["/robots.txt"] = (503, {}, "down")
    await crawls.crawl(site_id)
    assert len(await crawls.sources(site_id)) == 3
    site = await crawls.site_row(site_id)
    assert (site["last_crawl_status"], site["allow_decision"]) == ("unreachable", "allowed")
    job = await admin_conn.fetchrow(
        "SELECT status, error_code FROM jobs WHERE type = 'crawl_site' ORDER BY created_at DESC"
    )
    assert (job["status"], job["error_code"]) == ("failed", "site_unreachable")


async def test_due_crawls_are_queued_on_schedule(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    weekly = await crawls.approved(schedule="weekly")
    await crawls.run()
    assert await schedule_due_crawls(crawls.e.factory) == 0  # not due yet
    await admin_conn.execute(
        "UPDATE sites SET next_crawl_at = now() - interval '1 minute' WHERE id = $1", weekly
    )
    assert await schedule_due_crawls(crawls.e.factory) == 1
    assert await schedule_due_crawls(crawls.e.factory) == 0  # moved on a week
    queued = await admin_conn.fetchval(
        "SELECT count(*) FROM jobs WHERE type = 'crawl_site' AND status = 'queued'"
    )
    assert queued == 1
    await admin_conn.execute(
        "UPDATE sites SET schedule = 'none', next_crawl_at = now() - interval '1 day'"
    )
    assert await schedule_due_crawls(crawls.e.factory) == 0  # no schedule, no crawl


async def test_the_cli_path_registers_approves_and_waits_for_the_pages(crawls: Crawls) -> None:
    e = crawls.e
    spec = SiteSpec(ROOT + "/", "Synthetic", "Synthetic", "publisher-terms", ("sample-web",))
    proposed = await submit_site(
        e.factory, TAGS, spec, proposer_id=e.user_id, reviewer_id=None, resolve=resolver(PUBLIC)
    )
    assert (proposed.status, proposed.job_id) == ("proposed", None)
    queued = await submit_site(
        e.factory,
        TAGS,
        spec,
        proposer_id=e.user_id,
        reviewer_id=e.user_id,
        resolve=resolver(PUBLIC),
    )
    assert (queued.site_id, queued.status) == (proposed.site_id, "queued")

    async def run_jobs(_seconds: float) -> None:
        await crawls.run()

    status, results = await settle_site(e.factory, queued, sleep=run_jobs)
    assert status == "ok" and len(results) == 3
    settled = await settle(e.factory, results, sleep=run_jobs)
    assert {r.status for r in settled} == {"ingested"}
    again = await submit_site(
        e.factory,
        TAGS,
        spec,
        proposer_id=e.user_id,
        reviewer_id=e.user_id,
        resolve=resolver(PUBLIC),
    )
    assert again.status == "queued"  # an approved site: a crawl now


async def test_sites_are_shared_tables_the_app_cannot_delete_and_the_operator_cannot_read(
    crawls: Crawls, app_conn: asyncpg.Connection, admin_conn: asyncpg.Connection
) -> None:
    site_id = await crawls.approved()
    await crawls.run()
    # Operator-owned shared tables like sources: no tenant column, no RLS.
    for table in ("sites", "site_pages"):
        columns = await admin_conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
        )
        assert "tenant_id" not in {c["column_name"] for c in columns}
    # The application role reads and writes them, never deletes.
    assert await app_conn.fetchval("SELECT count(*) FROM site_pages WHERE site_id = $1", site_id)
    for table in ("sites", "site_pages"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(f"DELETE FROM {table}")
    # The operator console's role has no access to them at all.
    await app_conn.execute("SET ROLE askspore_operator")
    for table in ("sites", "site_pages"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.fetch(f"SELECT * FROM {table}")
