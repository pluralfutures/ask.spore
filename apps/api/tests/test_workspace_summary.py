"""P2B-05: the home page's workspace summary and its cache. Over HTTP against PostgreSQL
as the application role, Redis faked. Library changes are made through the application's own
sessions (the hook is on the session), not by SQL as the owner."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from typing import Any

import asyncpg
import pytest
from sqlalchemy import func, select, update

from app.content.models import Source
from app.core import cache, library_events
from app.core.db import create_engine, session_factory, tenant_session
from app.files.service import SUMMARY_KEY
from app.tenancy.models import INTERNAL_TENANT_ID, User
from app.tenancy.workspaces import Workspace
from tests.conftest import MigratedDatabase
from tests.fakes import FakeRedis
from tests.test_api import api
from tests.test_files import Files, files
from tests.test_tenancy import make_tenant

__all__ = ["api", "files"]  # fixtures

pytestmark = pytest.mark.usefixtures("database")

TAG = "p2b05-summary"  # no seeded source carries it: every test counts only its own rows
OTHER_TAG = "p2b05-other"


@pytest.fixture(autouse=True)
async def _own_workspace(files: Files) -> None:
    """A workspace on a tag of its own, and sources made on it unless a test says otherwise."""
    files.workspace = await files.api.world.new_workspace([TAG])
    make = files.source

    async def source(**kw: Any) -> uuid.UUID:
        kw.setdefault("tag", TAG)
        return await make(**kw)

    files.source = source  # type: ignore[method-assign]


async def summary(files: Files, workspace: uuid.UUID | None = None) -> dict[str, Any]:
    response = await files.api.request("GET", f"/workspaces/{workspace or files.workspace}/summary")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def set_published(files: Files, source: uuid.UUID, published: date | None) -> None:
    await files.admin.execute(
        "UPDATE sources SET published_on = $2 WHERE id = $1", source, published
    )


PAUSE = (
    "status = 'paused', paused_at = now(), paused_by = (SELECT id FROM users LIMIT 1), "
    "pause_reason = 'synthetic'"
)
WITHDRAW = "status = 'withdrawn', withdrawn_at = now(), withdrawal_reason = 'synthetic'"


def keys(redis: FakeRedis) -> list[str]:
    return [k for k in redis.store if SUMMARY_KEY in k]


# --- what it says -----------------------------------------------------------------------


async def test_counts_publishers_years_and_last_update_match_the_file_list(files: Files) -> None:
    a = await files.source(title="Synthetic A")
    b = await files.source(kind="docx", title="Synthetic B")
    c = await files.source(kind="pptx", title="Synthetic C")
    await files.admin.execute(
        "UPDATE sources SET publisher = 'Alpha Institute' WHERE id = ANY($1)", [a, b]
    )
    await files.admin.execute("UPDATE sources SET publisher = 'Beta Group' WHERE id = $1", c)
    await set_published(files, a, date(2019, 5, 1))
    await set_published(files, b, date(2025, 1, 1))
    await set_published(files, c, None)
    body = await summary(files)
    listed = (await files.api.request("GET", f"/workspaces/{files.workspace}/files")).json()
    assert body == {
        "document_count": 3,
        "publisher_count": 2,
        "top_publishers": ["Alpha Institute", "Beta Group"],
        "first_year": 2019,
        "last_year": 2025,
        "last_updated": date.today().isoformat(),
    }
    assert body["document_count"] == len(listed["files"]) + len(listed["sites"])


async def test_a_crawled_site_counts_as_one_document(files: Files) -> None:
    await files.source(title="Synthetic file")
    for n in range(4):
        await files.source(kind="markdown", stored=False, downloadable=False,
                           url=f"https://site-a.example/page-{n}")  # fmt: skip
    body = await summary(files)
    assert body["document_count"] == 2  # the file and the site
    assert body["publisher_count"] == 1


async def test_top_publishers_are_the_three_with_most_documents(files: Files) -> None:
    ids = [await files.source() for _ in range(6)]
    names = ["Zeta", "Zeta", "Zeta", "Mu", "Mu", "Alpha"]
    for source, name in zip(ids, names, strict=True):
        await files.admin.execute("UPDATE sources SET publisher = $2 WHERE id = $1", source, name)
    extra = await files.source()
    await files.admin.execute("UPDATE sources SET publisher = 'Beta' WHERE id = $1", extra)
    body = await summary(files)
    assert body["publisher_count"] == 4
    assert body["top_publishers"] == ["Zeta", "Mu", "Alpha"]  # ties: alphabetical


async def test_paused_withdrawn_and_other_tag_sources_are_not_counted(files: Files) -> None:
    await files.source(title="Counted")
    paused = await files.source()
    withdrawn = await files.source()
    await files.source(kind="pptx", tag=OTHER_TAG)  # outside the workspace's tags
    await files.admin.execute(f"UPDATE sources SET {PAUSE} WHERE id = $1", paused)
    await files.admin.execute(f"UPDATE sources SET {WITHDRAW} WHERE id = $1", withdrawn)
    assert (await summary(files))["document_count"] == 1


async def test_an_empty_workspace_has_no_figures(files: Files) -> None:
    assert await summary(files) == {
        "document_count": 0,
        "publisher_count": 0,
        "top_publishers": [],
        "first_year": None,
        "last_year": None,
        "last_updated": None,
    }


async def test_the_summary_carries_no_title_excerpt_or_ids(files: Files) -> None:
    source = await files.source(title="Synthetic Secret Title")
    body = await summary(files)
    text = json.dumps(body)
    assert "Synthetic Secret Title" not in text and str(source) not in text
    assert "ds-reports-0001" not in text
    assert set(body) == {
        "document_count", "publisher_count", "top_publishers",
        "first_year", "last_year", "last_updated",
    }  # fmt: skip


async def test_another_tenants_workspace_is_not_found_and_nothing_is_cached_for_it(
    files: Files, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    other = await make_tenant(admin_conn)
    foreign = await admin_conn.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", other.id)
    response = await files.api.request("GET", f"/workspaces/{foreign}/summary")
    assert response.status_code == 404
    assert keys(redis) == []
    # A key another tenant has cached is never served to this one.
    await cache.set(other.id, f"{SUMMARY_KEY}{foreign}", '{"document_count": 99}', 60)
    assert (await files.api.request("GET", f"/workspaces/{foreign}/summary")).status_code == 404


async def test_the_route_needs_a_signed_in_user(files: Files) -> None:
    response = await files.api.http.get(f"/api/v1/workspaces/{files.workspace}/summary")
    assert response.status_code in (401, 403)


# --- the cache --------------------------------------------------------------------------


async def test_the_summary_is_cached_under_a_tenant_prefixed_key(
    files: Files, redis: FakeRedis
) -> None:
    await files.source()
    first = await summary(files)
    key = f"t:{INTERNAL_TENANT_ID}:{SUMMARY_KEY}{files.workspace}"
    assert keys(redis) == [key]
    assert 0 < redis.ttls[key] <= 3600
    # A change that bypasses the application's session (SQL as the owner) is not seen:
    # the second read is the cached one.
    await files.source()
    assert await summary(files) == first


async def _library_change(files: Files, change: Any) -> None:
    async with tenant_session(files.api.app.state.db_factory, INTERNAL_TENANT_ID) as session:
        await change(session)
    await library_events.drain()


async def test_a_source_update_clears_the_summary_and_the_next_read_rebuilds_it(
    files: Files, redis: FakeRedis
) -> None:
    kept = await files.source()
    paused = await files.source()
    assert (await summary(files))["document_count"] == 2
    assert len(keys(redis)) == 1

    async def pause(session: Any) -> None:
        await session.execute(
            update(Source)
            .where(Source.id == paused)
            .values(
                status="paused",
                paused_at=func.now(),
                paused_by=select(User.id).limit(1).scalar_subquery(),
                pause_reason="synthetic",
            )
        )

    await _library_change(files, pause)
    assert keys(redis) == []
    assert (await summary(files))["document_count"] == 1
    assert len(keys(redis)) == 1
    assert kept


async def test_a_workspace_tag_change_clears_the_summary(
    files: Files, redis: FakeRedis, database: MigratedDatabase
) -> None:
    await files.source()
    await files.source(kind="pptx", tag=OTHER_TAG)
    assert (await summary(files))["document_count"] == 1
    assert len(keys(redis)) == 1

    # The operator console changes tags (an ORM object, as the operator role); the hook is
    # on the session, whoever writes.
    engine = create_engine(database.sqlalchemy_url)
    try:
        async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
            workspace = await session.get(Workspace, files.workspace)
            assert workspace is not None
            workspace.tag_ids = [TAG, OTHER_TAG]
        await library_events.drain()
    finally:
        await engine.dispose()
    assert keys(redis) == []
    assert (await summary(files))["document_count"] == 2


async def test_a_new_source_clears_the_summary(files: Files, redis: FakeRedis) -> None:
    await files.source()
    await summary(files)
    assert len(keys(redis)) == 1

    async def add(session: Any) -> None:
        session.add(
            Source(
                type="pdf",
                title="Synthetic new",
                publisher="Synthetic Publisher",
                licence_basis="public",
                tags=["sample-reports"],
                status="ingested",
                approved_at=func.now(),
            )
        )

    await _library_change(files, add)
    assert keys(redis) == []
    await files.admin.execute("DELETE FROM sources WHERE title = 'Synthetic new'")


async def test_a_workspace_deleted_leaves_no_summary_behind(
    files: Files, redis: FakeRedis, database: MigratedDatabase
) -> None:
    await files.source()
    await summary(files)
    assert len(keys(redis)) == 1
    # The application role cannot delete a workspace; the hook is on the session, whoever
    # deletes it (the termination purge runs as the owner).
    engine = create_engine(database.sqlalchemy_url)
    try:
        async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
            workspace = await session.get(Workspace, files.workspace)
            await session.delete(workspace)
        await library_events.drain()
    finally:
        await engine.dispose()
    assert keys(redis) == []


async def test_a_rolled_back_change_clears_nothing(files: Files, redis: FakeRedis) -> None:
    source = await files.source()
    await summary(files)
    with pytest.raises(RuntimeError):
        async with tenant_session(files.api.app.state.db_factory, INTERNAL_TENANT_ID) as session:
            await session.execute(update(Source).where(Source.id == source).values(title="x"))
            raise RuntimeError("synthetic failure")
    await library_events.drain()
    assert len(keys(redis)) == 1


async def test_a_source_change_clears_every_tenants_summaries_and_only_summaries(
    files: Files, redis: FakeRedis, admin_conn: asyncpg.Connection
) -> None:
    # The register is shared: a source ingested in the internal tenant changes what a
    # client tenant's workspace holds, so that tenant's cached summary goes too.
    other = await make_tenant(admin_conn)
    await cache.set(other.id, f"{SUMMARY_KEY}{uuid.uuid4()}", "{}", 60)
    await cache.set(other.id, "answer:corpus_only:abc", "{}", 60)
    source = await files.source()
    await summary(files)

    async def touch(session: Any) -> None:
        await session.execute(update(Source).where(Source.id == source).values(title="y"))

    await _library_change(files, touch)
    assert keys(redis) == []
    assert [k for k in redis.store if k.startswith(f"t:{other.id}:answer:")]  # not touched


async def test_a_burst_of_writes_runs_few_clears(
    files: Files, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await files.source()
    calls = 0
    real = cache.delete_prefix_all_tenants

    async def counted(prefix: str) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return await real(prefix)

    monkeypatch.setattr(cache, "delete_prefix_all_tenants", counted)
    for n in range(10):
        async with tenant_session(files.api.app.state.db_factory, INTERNAL_TENANT_ID) as session:
            await session.execute(update(Source).where(Source.id == source).values(title=str(n)))
    await library_events.drain()
    assert 1 <= calls <= 2


async def test_a_cache_fault_never_fails_the_read_or_the_write(
    files: Files, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await files.source()

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("synthetic cache outage")

    monkeypatch.setattr(cache, "get", broken)
    monkeypatch.setattr(cache, "set", broken)
    monkeypatch.setattr(cache, "delete_prefix_all_tenants", broken)
    assert (await summary(files))["document_count"] == 1

    async def touch(session: Any) -> None:
        await session.execute(update(Source).where(Source.id == source).values(title="z"))

    await _library_change(files, touch)  # the write commits; the failed clear is only logged


def test_every_table_the_summary_reads_is_tracked() -> None:
    assert library_events.LIBRARY_TABLES == {"sources", "workspaces"}


def test_the_hook_is_installed_whenever_the_database_module_is_imported() -> None:
    import app.core.db as db

    assert db.library_events is library_events
