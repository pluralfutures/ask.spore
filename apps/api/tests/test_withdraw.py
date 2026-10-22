"""P1b-03: re-ingestion and withdrawal (RAGFlow and Redis faked, database real)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app import cli
from app.content import worker
from app.content.ingest import SourceFile, SourceMetadata, load_path
from app.content.register import (
    RegisterError,
    TakedownItem,
    approve,
    record_takedown,
    replacement_candidates,
    request_withdrawal,
    takedown_due_on,
    takedown_queue,
    working_days_after,
)
from app.content.roles import RoleError
from app.content.withdraw import SUPERSEDED_REASON, purge_answer_cache
from app.core import cache
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import CONVERSATION_COLUMNS, CONVERSATION_DEFAULTS
from tests.fakes import FakeRedis
from tests.test_api import Harness, api
from tests.test_ingest import PDF, TAGS, Env, Ingest, content_user, env, meta, source_row

__all__ = ["api", "env"]  # the fixtures, imported for their use here

LINK = "https://example.org/tidewater-2026.pdf"


def linked(tag: str, url: str) -> SourceMetadata:
    """Metadata at a link of its own: a shared link would make one file replace another."""
    return SourceMetadata(**{**meta(tag).__dict__, "canonical_url": url})


def context(e: Env) -> worker.Context:
    return worker.Context(
        factory=e.factory,
        client=e.fake,  # type: ignore[arg-type]
        tags=TAGS,
        content_root=e.content_root,
        parse_poll_interval=0,
    )


async def run_queue(e: Env) -> None:
    handlers = worker.handlers(context(e))
    while await worker.run_once(e.factory, handlers):
        pass


async def other_tenant(admin_conn: asyncpg.Connection) -> tuple[UUID, UUID]:
    tenant_id = uuid.uuid4()
    await admin_conn.execute(
        "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Synthetic Client')",
        tenant_id,
        f"c-{tenant_id.hex[:12]}",
    )
    user_id = await admin_conn.fetchval(
        "INSERT INTO users (tenant_id, email, display_name) VALUES ($1, $2, 'Client') RETURNING id",
        tenant_id,
        f"user-{tenant_id.hex[:8]}@example.com",
    )
    await admin_conn.execute(
        "INSERT INTO workspaces (tenant_id, slug, name, default_model) "
        "VALUES ($1, 'default', 'Default', 'deepseek-v4.1-flash')",
        tenant_id,
    )
    return tenant_id, user_id


async def cite(
    admin_conn: asyncpg.Connection, tenant_id: UUID, user_id: UUID, source_id: UUID
) -> UUID:
    """A stored answer in ``tenant_id``'s history citing ``source_id``; the citation's ID."""
    conversation = await admin_conn.fetchval(
        f"INSERT INTO conversations (tenant_id, user_id, {CONVERSATION_COLUMNS}) "
        f"VALUES ($1, $2, {CONVERSATION_DEFAULTS}) RETURNING id",
        tenant_id,
        user_id,
    )
    message = await admin_conn.fetchval(
        "INSERT INTO messages (tenant_id, conversation_id, role, content, outcome) "
        "VALUES ($1, $2, 'assistant', 'Synthetic answer [1].', 'answered') RETURNING id",
        tenant_id,
        conversation,
    )
    citation_id: UUID = await admin_conn.fetchval(
        "INSERT INTO citations (tenant_id, message_id, marker, source_id, ragflow_chunk_id, "
        "excerpt) VALUES ($1, $2, 1, $3, 'chunk-old', 'Synthetic excerpt.') RETURNING id",
        tenant_id,
        message,
        source_id,
    )
    return citation_id


async def flags(admin_conn: asyncpg.Connection, citation_id: UUID) -> tuple[bool, bool]:
    row = await admin_conn.fetchrow(
        "SELECT superseded_at IS NOT NULL AS s, withdrawn_at IS NOT NULL AS w "
        "FROM citations WHERE id = $1",
        citation_id,
    )
    assert row is not None
    return row["s"], row["w"]


def cached(source_ids: list[str] | None, cited: list[str]) -> str:
    value: dict[str, Any] = {
        "answer": "Synthetic [1].",
        "outcome": "answered",
        "model": "m",
        "citations": [{"source_id": s, "marker": n + 1} for n, s in enumerate(cited)],
    }
    if source_ids is not None:
        value["source_ids"] = source_ids
    return json.dumps(value)


@pytest.fixture
async def history(admin_conn: asyncpg.Connection) -> Any:
    yield
    await admin_conn.execute("DELETE FROM conversations")


async def test_withdrawal_removes_the_source_from_every_dataset_history_and_cache(
    env: tuple[Env, Ingest],
    admin_conn: asyncpg.Connection,
    redis: FakeRedis,
    history: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    keep = await run(
        SourceFile("other.md", "markdown", b"# Synthetic other page"),
        linked("sample-web", "https://example.org/other"),
    )
    source, other = str(ingested.source_id), str(keep.source_id)
    assert len(ingested.document_ids) == 2
    client_tenant, client_user = await other_tenant(admin_conn)
    internal_user = e.user_id
    cited_here = await cite(admin_conn, INTERNAL_TENANT_ID, internal_user, ingested.source_id)
    cited_there = await cite(admin_conn, client_tenant, client_user, ingested.source_id)
    cited_other = await cite(admin_conn, client_tenant, client_user, keep.source_id)
    for tenant_id, key, value in (
        (INTERNAL_TENANT_ID, "answer:corpus_only:a", cached([source], [source])),
        (client_tenant, "answer:corpus_only:b", cached([other, source], [other, source])),
        (client_tenant, "answer:general_knowledge:c", cached(None, [source])),  # pre-P1b-03
        (client_tenant, "answer:corpus_only:d", cached([other], [other])),
        (INTERNAL_TENANT_ID, "answer:corpus_only:e", cached([], [])),
    ):
        await cache.set(tenant_id, key, value, 60)

    job_id = await request_withdrawal(
        e.factory, ingested.source_id, e.user_id, reason="licence ended (synthetic)"
    )
    row = await source_row(admin_conn, ingested.source_id)
    assert row["status"] == "ingested"  # nothing changes before the job runs
    await run_queue(e)

    # Every dataset: both documents deleted, the other source's untouched.
    assert set(ingested.document_ids.values()) <= set(e.fake.deleted)
    assert not set(ingested.document_ids.values()) & set(e.fake.documents)
    assert set(keep.document_ids.values()) <= set(e.fake.documents)
    # The register row.
    row = await source_row(admin_conn, ingested.source_id)
    assert (row["status"], row["withdrawal_reason"]) == ("withdrawn", "licence ended (synthetic)")
    assert row["withdrawn_at"] is not None
    assert (row["ragflow_document_ids"], row["stored_path"]) == ("{}", None)
    sha = row["file_sha256"]
    assert not (e.content_root / f"{sha[:2]}/{sha}.pdf").exists()  # our copy is gone
    # Stored history, in both tenants; other sources' citations untouched.
    assert await flags(admin_conn, cited_here) == (False, True)
    assert await flags(admin_conn, cited_there) == (False, True)
    assert await flags(admin_conn, cited_other) == (False, False)
    # The answer caches: every entry citing the source, in every tenant, and no other.
    assert sorted(k.rsplit(":", 1)[-1] for k in redis.store) == ["d", "e"]
    # The job and the audit trail.
    job = await admin_conn.fetchrow("SELECT status, error_code FROM jobs WHERE id = $1", job_id)
    assert (job["status"], job["error_code"]) == ("succeeded", None)
    trail = await admin_conn.fetch(
        "SELECT event, actor_user_id, metadata FROM audit_events "
        "WHERE metadata->>'source_id' = $1 ORDER BY created_at, id",
        source,
    )
    events = [(r["event"], json.loads(r["metadata"])) for r in trail]
    assert [name for name, _ in events][-2:] == ["source.withdrawal_requested", "source.withdrawn"]
    done = events[-1][1]
    assert (done["before"], done["after"], done["outcome"], done["count"]) == (
        {"status": "ingested"},
        {"status": "withdrawn"},
        "withdrawn",
        2,
    )
    assert "licence ended" not in json.dumps(events)  # the reason stays on the row
    assert "licence ended" not in capsys.readouterr().out


async def test_withdrawal_is_for_reviewers_and_ingested_sources_only(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    pending = await run(load_path(PDF), meta("sample-reports"), reviewer_id=None)
    assert pending.status == "proposed"
    with pytest.raises(RegisterError) as refused:
        await request_withdrawal(e.factory, pending.source_id, e.user_id, reason="x")
    assert refused.value.code == "not_withdrawable"
    await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError):
        await request_withdrawal(e.factory, pending.source_id, e.user_id, reason="x")
    assert await admin_conn.fetchval("SELECT count(*) FROM jobs") == 0


async def test_a_withdrawal_that_cannot_reach_ragflow_is_retried(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    job_id = await request_withdrawal(e.factory, ingested.source_id, e.user_id, reason="r")
    from app.retrieval.ragflow import RagflowError

    e.fake.fail_delete = RagflowError("delete_documents", "unreachable")
    await run_queue(e)
    job = await admin_conn.fetchrow("SELECT status, error_code FROM jobs WHERE id = $1", job_id)
    assert (job["status"], job["error_code"]) == ("queued", "ragflow_unreachable")
    assert (await source_row(admin_conn, ingested.source_id))["status"] == "ingested"

    e.fake.fail_delete = None
    await admin_conn.execute("UPDATE jobs SET run_after = now()")
    await run_queue(e)
    assert (await source_row(admin_conn, ingested.source_id))["status"] == "withdrawn"


async def test_reingesting_a_changed_file_supersedes_the_old_version_when_the_reviewer_says_so(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis, history: None
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    citation = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, first.source_id)
    old = str(first.source_id)
    await cache.set(INTERNAL_TENANT_ID, "answer:corpus_only:x", cached([old], [old]), 60)

    changed = SourceFile("tidewater-v2.pdf", "pdf", PDF.read_bytes() + b"\n% revised")
    second = await run(changed, meta("sample-reports", "sample-web"))  # same canonical link
    # Owner decision 4: flagged for the reviewer, nothing replaced or queued unasked.
    assert (second.status, second.error_code) == ("proposed", "possible_replacement")
    assert (await source_row(admin_conn, second.source_id))["supersedes_id"] is None
    assert await admin_conn.fetchval("SELECT count(*) FROM jobs WHERE status = 'queued'") == 0

    await approve(e.factory, second.source_id, e.user_id, replaces=first.source_id)
    await run_queue(e)
    new_row = await source_row(admin_conn, second.source_id)
    assert (new_row["status"], new_row["supersedes_id"]) == ("ingested", first.source_id)
    assert new_row["canonical_url"] == LINK
    approval = await admin_conn.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'source.approved' "
        "AND metadata->>'source_id' = $1",
        str(second.source_id),
    )
    assert json.loads(approval)["replaces"] == old

    old_row = await source_row(admin_conn, first.source_id)
    assert (old_row["status"], old_row["withdrawal_reason"]) == ("withdrawn", SUPERSEDED_REASON)
    assert not set(first.document_ids.values()) & set(e.fake.documents)  # old chunks gone
    assert set(json.loads(new_row["ragflow_document_ids"]).values()) <= set(e.fake.documents)
    assert await flags(admin_conn, citation) == (True, False)  # superseded, not withdrawn
    assert redis.store == {}
    # The new version's own staged copy is kept.
    sha = new_row["file_sha256"]
    assert (e.content_root / f"{sha[:2]}/{sha}.pdf").is_file()


async def test_keep_both_leaves_the_ingested_source_in_place(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    other = await run(
        SourceFile("other.pdf", "pdf", PDF.read_bytes() + b"\n% another report"),
        meta("sample-reports", title="Another report at the landing page"),
    )
    assert other.error_code == "possible_replacement"
    await approve(e.factory, other.source_id, e.user_id, keep_both=True)
    await run_queue(e)
    assert (await source_row(admin_conn, first.source_id))["status"] == "ingested"
    second = await source_row(admin_conn, other.source_id)
    assert (second["status"], second["supersedes_id"]) == ("ingested", None)
    assert not await admin_conn.fetchval("SELECT count(*) FROM jobs WHERE type = 'withdraw_source'")
    approval = await admin_conn.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'source.approved' "
        "AND metadata->>'source_id' = $1",
        str(other.source_id),
    )
    assert json.loads(approval)["keep_both"] is True


async def test_a_possible_replacement_needs_a_valid_choice(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    pages = [SourceFile(f"p{n}.md", "markdown", f"# Synthetic page {n}".encode()) for n in range(4)]
    one = await run(pages[0], meta("sample-web"))
    two = await run(pages[1], meta("sample-web"), reviewer_id=None)
    await approve(e.factory, two.source_id, e.user_id, keep_both=True)
    await run_queue(e)
    third = await run(pages[2], meta("sample-web"), reviewer_id=None)
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        assert await replacement_candidates(session, LINK, exclude=third.source_id) == [
            one.source_id,
            two.source_id,
        ]
    for kwargs, code in (
        ({}, "replacement_choice_required"),
        ({"replaces": third.source_id}, "not_a_replacement_candidate"),
        ({"replaces": uuid.uuid4()}, "not_a_replacement_candidate"),
        ({"replaces": one.source_id, "keep_both": True}, "replace_or_keep_both"),
    ):
        with pytest.raises(RegisterError) as refused:
            await approve(e.factory, third.source_id, e.user_id, **kwargs)
        assert refused.value.code == code
    assert (await source_row(admin_conn, third.source_id))["status"] == "proposed"
    await approve(e.factory, third.source_id, e.user_id, replaces=two.source_id)
    # A second proposal cannot replace the same source again.
    rival = await run(
        SourceFile("p5.md", "markdown", b"# Synthetic 5"), meta("sample-web"), reviewer_id=None
    )
    with pytest.raises(RegisterError) as twice:
        await approve(e.factory, rival.source_id, e.user_id, replaces=two.source_id)
    assert twice.value.code == "already_being_replaced"
    assert (await source_row(admin_conn, third.source_id))["supersedes_id"] == two.source_id
    # A link no ingested source has needs no choice.
    fourth = await run(
        SourceFile("p4.md", "markdown", b"# Synthetic 4"),
        linked("sample-web", "https://x.example/"),
    )
    assert fourth.status == "ingested"


async def test_withdrawal_on_licence_grounds_blanks_the_stored_excerpts(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis, history: None
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    changed = SourceFile("tidewater-v2.pdf", "pdf", PDF.read_bytes() + b"\n% revised")
    second = await run(changed, meta("sample-reports"))
    old_citation = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, first.source_id)
    await approve(e.factory, second.source_id, e.user_id, replaces=first.source_id)
    await run_queue(e)
    client_tenant, client_user = await other_tenant(admin_conn)
    here = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, second.source_id)
    there = await cite(admin_conn, client_tenant, client_user, second.source_id)
    keep = await run(
        SourceFile("other.md", "markdown", b"# Synthetic other page"),
        linked("sample-web", "https://example.org/other"),
    )
    unrelated = await cite(admin_conn, client_tenant, client_user, keep.source_id)

    await record_takedown(
        e.factory,
        second.source_id,
        e.user_id,
        reference="TD-LIC-1",
        requested_on=date(2026, 10, 22),
        licence_breach=False,
        licence_grounds=True,
    )
    await request_withdrawal(e.factory, second.source_id, e.user_id, reason="licence withdrawn")
    await run_queue(e)

    async def citation(citation_id: UUID) -> asyncpg.Record:
        row = await admin_conn.fetchrow(
            "SELECT excerpt, withdrawn_at, superseded_at, marker, source_id "
            "FROM citations WHERE id = $1",
            citation_id,
        )
        assert row is not None
        return row

    for blanked in (here, there):
        row = await citation(blanked)
        assert row["excerpt"] == ""  # the licensed text is gone
        assert row["withdrawn_at"] is not None  # still labelled "withdrawn"
        assert row["source_id"] == second.source_id and row["marker"] == 1
    # The earlier version it replaced carried the same licensed text.
    old = await citation(old_citation)
    assert (old["excerpt"], old["superseded_at"] is not None) == ("", True)
    assert (await citation(unrelated))["excerpt"] == "Synthetic excerpt."
    done = await admin_conn.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'source.withdrawn' "
        "AND metadata->>'source_id' = $1",
        str(second.source_id),
    )
    assert json.loads(done)["excerpts_blanked"] is True


@pytest.mark.parametrize("takedown", [None, "TD-OTHER-1"])
async def test_other_withdrawals_keep_the_stored_excerpts(
    env: tuple[Env, Ingest],
    admin_conn: asyncpg.Connection,
    redis: FakeRedis,
    history: None,
    takedown: str | None,
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports"))
    cited = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, ingested.source_id)
    if takedown:  # a takedown, but not on licence grounds (e.g. a privacy request)
        await record_takedown(
            e.factory,
            ingested.source_id,
            e.user_id,
            reference=takedown,
            requested_on=date(2026, 10, 22),
            licence_breach=False,
        )
    await request_withdrawal(e.factory, ingested.source_id, e.user_id, reason="withdrawn")
    await run_queue(e)
    row = await admin_conn.fetchrow(
        "SELECT excerpt, withdrawn_at FROM citations WHERE id = $1", cited
    )
    assert row["excerpt"] == "Synthetic excerpt." and row["withdrawn_at"] is not None
    done = await admin_conn.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'source.withdrawn' "
        "AND metadata->>'source_id' = $1",
        str(ingested.source_id),
    )
    assert json.loads(done)["excerpts_blanked"] is False


async def test_a_licence_breach_is_on_licence_grounds(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports"))
    await record_takedown(
        e.factory,
        ingested.source_id,
        e.user_id,
        reference="INT-9",
        requested_on=date(2026, 10, 22),
        licence_breach=True,
    )
    row = await source_row(admin_conn, ingested.source_id)
    assert row["takedown_licence_grounds"] is True
    with pytest.raises(asyncpg.CheckViolationError):
        await admin_conn.execute(
            "UPDATE sources SET takedown_licence_grounds = true, takedown_reference = NULL, "
            "takedown_requested_on = NULL, takedown_due_on = NULL WHERE id = $1",
            ingested.source_id,
        )


async def test_a_document_ragflow_no_longer_has_counts_as_deleted(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    gone = next(iter(ingested.document_ids.values()))
    del e.fake.documents[gone]  # deleted in the RAGFlow UI, or by an earlier attempt
    job_id = await request_withdrawal(e.factory, ingested.source_id, e.user_id, reason="r")
    await run_queue(e)
    job = await admin_conn.fetchrow("SELECT status, attempts FROM jobs WHERE id = $1", job_id)
    assert (job["status"], job["attempts"]) == ("succeeded", 1)
    row = await source_row(admin_conn, ingested.source_id)
    assert (row["status"], row["ragflow_document_ids"]) == ("withdrawn", "{}")


async def test_superseded_and_withdrawn_citations_are_flagged_in_the_read_route(
    api: Harness, admin_conn: asyncpg.Connection
) -> None:
    from app.content.withdraw import flag_citations

    conversation = await api.conversation()
    await api.ask(conversation, "How did capacity change?", "Capacity grew [1].")
    body = (await api.request("GET", f"/conversations/{conversation}")).json()
    [citation] = body["messages"][1]["citations"]
    assert (citation["superseded"], citation["withdrawn"]) == (False, False)

    source_id = UUID(citation["source_id"])
    factory = api.app.state.db_factory
    assert await flag_citations(factory, source_id, "superseded") == 1
    body = (await api.request("GET", f"/conversations/{conversation}")).json()
    [citation] = body["messages"][1]["citations"]
    assert (citation["superseded"], citation["withdrawn"]) == (True, False)
    assert citation["excerpt"]  # the stored citation itself is unchanged

    assert await flag_citations(factory, source_id, "withdrawn") == 1
    assert await flag_citations(factory, source_id, "withdrawn") == 0  # idempotent
    body = (await api.request("GET", f"/conversations/{conversation}")).json()
    [citation] = body["messages"][1]["citations"]
    assert (citation["superseded"], citation["withdrawn"]) == (True, True)


async def test_answer_cache_values_record_their_source_ids_and_are_purged(
    api: Harness, redis: FakeRedis
) -> None:
    conversation = await api.conversation()
    await api.ask(conversation, "How did capacity change?", "Capacity grew [1].")
    [(key, raw)] = [(k, v) for k, v in redis.store.items() if ":answer:" in k]
    value = json.loads(raw)
    cited = sorted({c["source_id"] for c in value["citations"]})
    assert value["source_ids"] == cited != []
    assert await purge_answer_cache(api.app.state.db_factory, {str(uuid.uuid4())}) == 0
    assert key in redis.store
    assert await purge_answer_cache(api.app.state.db_factory, set(cited)) == 1
    assert key not in redis.store


async def test_cache_scan_stays_in_one_tenants_namespace(redis: FakeRedis) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await cache.set(a, "answer:1", "x", 60)
    await cache.set(b, "answer:2", "y", 60)
    await cache.set(a, "other:3", "z", 60)
    assert [kv async for kv in cache.scan(a, "answer:")] == [("answer:1", "x")]
    for bad in ("", "answer:*", "a?", "[x]"):
        with pytest.raises(ValueError):
            [kv async for kv in cache.scan(a, bad)]
    await cache.delete(a, "answer:1")
    assert await cache.get(a, "answer:1") is None
    assert await cache.get(b, "answer:2") == "y"


async def test_the_content_role_sees_identifiers_and_flags_only(
    env: tuple[Env, Ingest],
    app_conn: asyncpg.Connection,
    admin_conn: asyncpg.Connection,
    history: None,
) -> None:
    e, run = env
    ingested = await run(load_path(PDF), meta("sample-reports"))
    cited = await cite(admin_conn, INTERNAL_TENANT_ID, e.user_id, ingested.source_id)
    await app_conn.execute("SET ROLE askspore_content")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.fetch("SELECT excerpt FROM citations")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.fetch("SELECT content FROM messages")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.fetch("SELECT slug FROM tenants")
    # It may blank an excerpt (revision 0023, licence-ground takedowns), never write one.
    with pytest.raises(asyncpg.RaiseError, match="may only blank"):
        await app_conn.execute("UPDATE citations SET excerpt = 'x'")
    assert await app_conn.execute("UPDATE citations SET excerpt = ''") == "UPDATE 1"
    assert await admin_conn.fetchval("SELECT excerpt FROM citations WHERE id = $1", cited) == ""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE citations SET marker = 2")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM citations")
    assert await app_conn.fetchval("SELECT count(*) FROM tenants") >= 1
    role = await admin_conn.fetchrow(
        "SELECT rolcanlogin, rolbypassrls, rolsuper FROM pg_roles "
        "WHERE rolname = 'askspore_content'"
    )
    assert role is not None and not any(role.values())


def test_takedown_due_date_counts_working_days() -> None:
    # Fri Oct 23, 2026 + 10 working days = Fri Nov 6 (two weekends skipped).
    assert working_days_after(date(2026, 10, 23), 10) == date(2026, 11, 6)
    assert working_days_after(date(2026, 10, 21), 10) == date(2026, 11, 4)  # Wednesday
    assert working_days_after(date(2026, 10, 24), 10) == date(2026, 11, 6)  # Saturday
    assert working_days_after(date(2026, 10, 21), 0) == date(2026, 10, 21)
    assert takedown_due_on(date(2026, 10, 23), licence_breach=False) == date(2026, 11, 6)
    # A licence breach we find ourselves is due at once.
    assert takedown_due_on(date(2026, 10, 23), licence_breach=True) == date(2026, 10, 23)
    item = TakedownItem(uuid.uuid4(), "ingested", "TD-1", date(2026, 10, 23), date(2026, 11, 6))
    assert item.working_days_left(date(2026, 10, 23)) == 10
    assert item.working_days_left(date(2026, 11, 6)) == 0
    assert item.working_days_left(date(2026, 11, 9)) == -1  # overdue by one working day


async def test_takedown_queue_lists_requests_by_due_date(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    second = await run(
        SourceFile("p.md", "markdown", b"# Synthetic"), linked("sample-web", "https://x.example/p")
    )
    due = await record_takedown(
        e.factory,
        first.source_id,
        e.user_id,
        reference="TD-2026-001",
        requested_on=date(2026, 10, 21),
        licence_breach=False,
    )
    assert due == date(2026, 11, 4)
    assert await record_takedown(
        e.factory,
        second.source_id,
        e.user_id,
        reference="INT-7",
        requested_on=date(2026, 10, 22),
        licence_breach=True,
    ) == date(2026, 10, 22)
    with pytest.raises(RegisterError):
        await record_takedown(
            e.factory,
            first.source_id,
            e.user_id,
            reference=" ",
            requested_on=date(2026, 10, 21),
            licence_breach=False,
        )
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        queue = await takedown_queue(session)
    assert [(i.source_id, i.reference, i.due_on) for i in queue] == [
        (second.source_id, "INT-7", date(2026, 10, 22)),
        (first.source_id, "TD-2026-001", date(2026, 11, 4)),
    ]
    audit = await admin_conn.fetchrow(
        "SELECT metadata FROM audit_events WHERE event = 'source.takedown_recorded' "
        "AND metadata->>'source_id' = $1",
        str(first.source_id),
    )
    assert json.loads(audit["metadata"])["after"] == {
        "takedown_reference": "TD-2026-001",
        "takedown_due_on": "2026-11-04",
        "takedown_licence_grounds": False,
    }
    # Withdrawn sources leave the queue.
    await request_withdrawal(e.factory, second.source_id, e.user_id, reason="licence breach")
    await run_queue(e)
    async with tenant_session(e.factory, INTERNAL_TENANT_ID) as session:
        assert [i.source_id for i in await takedown_queue(session)] == [first.source_id]
    with pytest.raises(asyncpg.CheckViolationError):  # a due date needs a reference
        await admin_conn.execute(
            "UPDATE sources SET takedown_reference = NULL WHERE id = $1", first.source_id
        )


def test_cli_withdraw_and_takedown_flags() -> None:
    source = str(uuid.UUID(int=5))
    args = cli.build_parser().parse_args(
        ["sources", "withdraw", source, "--as", "r@example.org", "--reason", "takedown", "--wait"]
    )
    assert (args.sources_command, args.reason, args.wait) == ("withdraw", "takedown", True)
    args = cli.build_parser().parse_args(
        [
            "sources",
            "takedown",
            source,
            "--as",
            "r@example.org",
            "--reference",
            "TD-1",
            "--requested-on",
            "2026-10-21",
            "--licence-breach",
        ]
    )
    assert (args.reference, args.requested_on, args.licence_breach) == (
        "TD-1",
        date(2026, 10, 21),
        True,
    )
