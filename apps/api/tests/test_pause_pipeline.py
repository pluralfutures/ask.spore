"""P2A-03: pause and the content pipeline (RAGFlow, the site and Redis faked, database
real). Negative cases first."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import pytest

from app.chat.package import provenance_by_document
from app.content.ingest import SourceFile, load_path
from app.content.register import (
    RegisterError,
    approve_retag,
    pause,
    request_withdrawal,
    resume,
)
from app.content.sites import withdraw_site
from app.content.submit import submit
from app.core import cache
from app.retrieval.ragflow import RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fakes import FakeRedis
from tests.test_crawler import ROOT, html
from tests.test_ingest import PDF, TAGS, Env, Ingest, env, meta, source_row
from tests.test_pause import REASON, events, retrievable
from tests.test_sites import DATED, Crawls, crawls
from tests.test_withdraw import cached, cite, flags, other_tenant, run_queue

__all__ = ["crawls", "env"]  # the fixtures, imported for their use here


async def web_tenant(admin_conn: asyncpg.Connection) -> UUID:
    """A client tenant whose only workspace holds ``sample-web``."""
    tenant_id, _ = await other_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-web'] WHERE tenant_id = $1", tenant_id
    )
    return tenant_id


def disabled(e: Env, row: asyncpg.Record) -> list[bool]:
    ids = json.loads(row["ragflow_document_ids"]).values()
    return [e.fake.documents[d].enabled is False for d in ids]


# Refusals.


async def test_a_retag_of_a_paused_source_is_refused(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await pause(e.factory, e.fake, first.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    uploads = len(e.fake.uploads)

    with pytest.raises(RegisterError, match=r"^paused$"):
        await run(load_path(PDF), meta("sample-reports", "sample-web"))  # with a reviewer
    pending = await submit(
        e.factory,
        TAGS,
        load_path(PDF),
        meta("sample-reports", "sample-web"),
        content_root=e.content_root,
        proposer_id=e.user_id,
        reviewer_id=None,
    )
    assert (pending.source_id, pending.status) == (first.source_id, "retag_pending")
    with pytest.raises(RegisterError, match=r"^paused$"):
        await approve_retag(
            e.factory, first.source_id, e.user_id, ["sample-web"], downloadable=False
        )
    assert len(e.fake.uploads) == uploads
    row = await source_row(admin_conn, first.source_id)
    assert (row["status"], list(row["tags"])) == ("paused", ["sample-reports"])
    # The same content again, in the same tag: nothing to do, the source stays paused.
    again = await run(load_path(PDF), meta("sample-reports"))
    assert (again.source_id, again.status) == (first.source_id, "duplicate")


async def test_a_pause_waits_for_an_ingestion_in_flight(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await approve_retag(e.factory, first.source_id, e.user_id, ["sample-web"], downloadable=False)
    with pytest.raises(RegisterError, match="ingestion_in_progress"):
        await pause(e.factory, e.fake, first.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert e.fake.toggles == []
    await run_queue(e)
    paused = await pause(e.factory, e.fake, first.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert paused.documents == 2  # the re-tag's document is paused too


async def test_an_inherited_pause_that_cannot_be_applied_fails_the_new_version(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    old = (await crawls.sources(site_id))[ROOT + "/a"]
    await pause(e.factory, e.fake, old["id"], e.user_id, reason=REASON)  # type: ignore[arg-type]
    e.fake.fail_toggle[e.datasets["sample-web"]] = RagflowError("set_document_enabled", 500)

    crawls.site.pages["/a"] = html("Page A", "Alpha revised", DATED)
    await crawls.crawl(site_id)
    new = await admin_conn.fetchrow("SELECT * FROM sources WHERE supersedes_id = $1", old["id"])
    assert (new["status"], new["error"], new["ragflow_document_ids"]) == (
        "failed",
        "the inherited pause could not be applied (ragflow_500)",
        "{}",
    )
    # The new version's documents were uploaded, then deleted when the pause failed.
    tag = new["id"].hex[:8]
    assert [name for _, name, _ in e.fake.uploads if tag in name]
    assert not [d for d in e.fake.documents.values() if tag in d.name]
    assert (await source_row(admin_conn, old["id"]))["status"] == "paused"  # not replaced
    page = (await crawls.pages(site_id))[ROOT + "/a"]
    assert (page["state"], page["source_id"]) == ("live", new["id"])
    # Neither version is retrievable.
    tenant = await web_tenant(admin_conn)

    class Old:
        document_ids = json.loads(old["ragflow_document_ids"])

    assert await retrievable(e.fake, e.factory, tenant, Old) == 0  # type: ignore[arg-type]


async def test_a_new_version_of_a_paused_source_has_no_provenance_while_it_parses(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await pause(e.factory, e.fake, first.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    # An approved successor whose document RAGFlow already holds and returns, mid-parse.
    successor = await admin_conn.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, tags, status, "
        "ragflow_document_ids, approved_at, supersedes_id) VALUES ('pdf', 'v2', 'p', 'l', "
        "ARRAY['sample-reports'], 'approved', $1::jsonb, now(), $2) RETURNING id",
        json.dumps({e.datasets["sample-reports"]: "doc-v2-parsing"}),
        first.source_id,
    )
    async with e.factory() as session:
        assert await provenance_by_document(session, ["doc-v2-parsing"]) == {}
    await resume(e.factory, e.fake, first.source_id, e.user_id)  # type: ignore[arg-type]
    async with e.factory() as session:
        found = await provenance_by_document(session, ["doc-v2-parsing"])
    assert found["doc-v2-parsing"].source_id == successor


# The pipeline.


async def test_a_changed_paused_page_yields_a_paused_successor_and_no_retrievable_chunk(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    old = (await crawls.sources(site_id))[ROOT + "/a"]
    await pause(e.factory, e.fake, old["id"], e.user_id, reason=REASON)  # type: ignore[arg-type]
    tenant = await web_tenant(admin_conn)

    crawls.site.pages["/a"] = html("Page A", "Alpha revised", DATED)
    await crawls.crawl(site_id)
    new = (await crawls.sources(site_id))[ROOT + "/a"]
    assert new["id"] != old["id"] and new["supersedes_id"] == old["id"]
    assert (new["status"], new["pause_reason"], new["paused_by"]) == ("paused", REASON, e.user_id)
    assert all(disabled(e, new))
    old_row = await source_row(admin_conn, old["id"])
    assert old_row["status"] == "withdrawn"  # replaced, as for an ingested page
    page = (await crawls.pages(site_id))[ROOT + "/a"]
    assert (page["state"], page["source_id"]) == ("live", new["id"])

    class Of:
        document_ids = json.loads(new["ragflow_document_ids"])

    assert await retrievable(e.fake, e.factory, tenant, Of) == 0  # type: ignore[arg-type]
    ingested = dict(await events(admin_conn, new["id"]))["source.ingested"]
    assert (ingested["after"], ingested["outcome"]) == ({"status": "paused"}, "pause_inherited")

    # A later unchanged crawl leaves it paused; the reviewer resumes it explicitly.
    await crawls.crawl(site_id)
    assert (await source_row(admin_conn, new["id"]))["status"] == "paused"
    await resume(e.factory, e.fake, new["id"], e.user_id)  # type: ignore[arg-type]
    assert await retrievable(e.fake, e.factory, tenant, Of) == 3  # type: ignore[arg-type]


async def test_a_reingestion_of_a_paused_source_at_the_same_link_and_title_is_paused(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await pause(e.factory, e.fake, first.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    second = await run(
        SourceFile("v2.pdf", "pdf", b"%PDF-1.4 synthetic v2"), meta("sample-reports")
    )
    assert second.status == "ingested" and second.paused
    row = await source_row(admin_conn, second.source_id)
    assert (row["status"], row["supersedes_id"], row["pause_reason"]) == (
        "paused",
        first.source_id,
        REASON,
    )
    assert all(disabled(e, row))
    await run_queue(e)  # the supersession of the first version
    assert (await source_row(admin_conn, first.source_id))["status"] == "withdrawn"


async def test_withdrawing_a_paused_source_runs_the_full_cascade_and_blanks_excerpts(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    e, run = env
    source = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    client_tenant, client_user = await other_tenant(admin_conn)
    here = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, source.source_id)
    there = await cite(admin_conn, client_tenant, client_user, source.source_id)
    await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    sid = str(source.source_id)
    await cache.set(client_tenant, "answer:corpus_only:late", cached([sid], [sid]), 60)

    await request_withdrawal(e.factory, source.source_id, e.user_id, reason="takedown (synthetic)")
    await run_queue(e)
    row = await source_row(admin_conn, source.source_id)
    assert (row["status"], row["withdrawal_reason"]) == ("withdrawn", "takedown (synthetic)")
    # A withdrawal ends the pause and carries its own reason; the pause fields are cleared.
    assert (row["paused_at"], row["paused_by"], row["pause_reason"]) == (None, None, None)
    assert (row["ragflow_document_ids"], row["stored_path"]) == ("{}", None)
    assert set(source.document_ids.values()) <= set(e.fake.deleted)
    sha = row["file_sha256"]
    assert not (e.content_root / f"{sha[:2]}/{sha}.pdf").exists()
    for citation in (here, there):
        assert await flags(admin_conn, citation) == (False, True)
        assert (
            await admin_conn.fetchval("SELECT excerpt FROM citations WHERE id = $1", citation) == ""
        )
    assert redis.store == {}
    withdrawn = dict(await events(admin_conn, source.source_id))["source.withdrawn"]
    assert (withdrawn["before"], withdrawn["excerpts_blanked"]) == ({"status": "paused"}, True)
    await admin_conn.execute("DELETE FROM conversations")


async def test_a_paused_page_that_left_the_site_is_withdrawn(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    gone = (await crawls.sources(site_id))[ROOT + "/b"]
    await pause(e.factory, e.fake, gone["id"], e.user_id, reason=REASON)  # type: ignore[arg-type]
    del crawls.site.pages["/b"]
    await crawls.crawl(site_id)
    row = await source_row(admin_conn, gone["id"])
    assert (row["status"], row["withdrawal_reason"]) == (
        "withdrawn",
        "page removed from the site (HTTP 404)",
    )


async def test_a_withdrawn_site_withdraws_its_paused_pages(
    crawls: Crawls, admin_conn: asyncpg.Connection
) -> None:
    e = crawls.e
    site_id = await crawls.approved()
    await crawls.run()
    paused = (await crawls.sources(site_id))[ROOT + "/a"]
    await pause(e.factory, e.fake, paused["id"], e.user_id, reason=REASON)  # type: ignore[arg-type]
    await withdraw_site(e.factory, site_id, e.user_id, reason="site retired (synthetic)")
    await crawls.run()
    assert (await source_row(admin_conn, paused["id"]))["status"] == "withdrawn"
    assert not set(json.loads(paused["ragflow_document_ids"]).values()) & set(e.fake.documents)
