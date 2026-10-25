"""P2A-01: a reviewer pauses and resumes an ingested source (RAGFlow and Redis faked,
database real). Negative cases first."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app import cli
from app.chat.package import resolve_package, workspace_package
from app.content import register, worker
from app.content.datasets import StatusMismatch, status_mismatches
from app.content.ingest import IngestResult, SourceFile, load_path
from app.content.register import (
    RegisterError,
    approve,
    pause,
    record_takedown,
    request_withdrawal,
    resume,
    retry,
    takedown_queue,
)
from app.content.roles import RoleError
from app.core import cache
from app.core.config import load_settings
from app.core.db import tenant_session
from app.retrieval.ragflow import RagflowClient, RagflowError
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase
from tests.fakes import FakeRedis
from tests.ragflow_fake import FakeRagflow
from tests.test_datasets_sync import ENV
from tests.test_ingest import PDF, Env, Ingest, content_user, env, meta, source_row
from tests.test_withdraw import cached, linked, other_tenant, run_queue

__all__ = ["env"]  # the fixture, imported for its use here

REASON = "rights check pending (synthetic)"


async def two_datasets(run: Ingest) -> IngestResult:
    """The sample PDF ingested into two datasets (two RAGFlow documents)."""
    result = await run(load_path(PDF), meta("sample-reports", "sample-web"))
    assert result.status == "ingested" and len(result.document_ids) == 2
    return result


async def events(admin_conn: asyncpg.Connection, source_id: UUID) -> list[tuple[str, Any]]:
    rows = await admin_conn.fetch(
        "SELECT event, metadata FROM audit_events WHERE metadata->>'source_id' = $1 "
        "ORDER BY created_at, id",
        str(source_id),
    )
    return [(r["event"], json.loads(r["metadata"])) for r in rows]


def enabled(fake: FakeRagflow, result: IngestResult) -> list[bool | None]:
    return [fake.documents[d].enabled for _, d in sorted(result.document_ids.items())]


async def retrievable(
    fake: FakeRagflow, factory: Any, tenant_id: UUID, source: IngestResult
) -> int:
    """Chunks of ``source`` retrieved through the tenant's only workspace."""
    async with tenant_session(factory, tenant_id) as session:
        workspace_id = await session.scalar(text("SELECT id FROM workspaces LIMIT 1"))
        package = await workspace_package(session, workspace_id)
    chunks = await fake.retrieve_chunks(
        dataset_ids=package.dataset_ids, question="q", top_k=100, similarity_threshold=0.2
    )
    return sum(1 for c in chunks if c.document_id in source.document_ids.values())


# Refusals.


async def test_a_non_reviewer_cannot_pause_or_resume(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source = await two_datasets(run)
    editor = await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError):
        await pause(e.factory, e.fake, source.source_id, editor, reason=REASON)  # type: ignore[arg-type]
    await content_user(admin_conn)  # no content role at all
    with pytest.raises(RoleError):
        await pause(e.factory, e.fake, source.source_id, editor, reason=REASON)  # type: ignore[arg-type]
    assert e.fake.toggles == []
    assert (await source_row(admin_conn, source.source_id))["status"] == "ingested"

    reviewer = await content_user(admin_conn, "content_reviewer")
    await pause(e.factory, e.fake, source.source_id, reviewer, reason=REASON)  # type: ignore[arg-type]
    await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError):
        await resume(e.factory, e.fake, source.source_id, editor)  # type: ignore[arg-type]
    assert (await source_row(admin_conn, source.source_id))["status"] == "paused"
    assert [event for event, _ in await events(admin_conn, source.source_id)].count(
        "source.resumed"
    ) == 0


async def test_only_an_ingested_source_pauses_and_only_a_paused_one_resumes(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    fake: Any = e.fake
    proposed = await run(
        SourceFile("p.md", "markdown", b"# Synthetic proposal"),
        linked("sample-web", "https://example.org/p"),
        reviewer_id=None,
    )
    assert (await source_row(admin_conn, proposed.source_id))["status"] == "proposed"
    with pytest.raises(RegisterError, match="not_ingested"):
        await pause(e.factory, fake, proposed.source_id, e.user_id, reason=REASON)

    source = await two_datasets(run)
    with pytest.raises(RegisterError, match="not_paused"):
        await resume(e.factory, fake, source.source_id, e.user_id)
    with pytest.raises(RegisterError, match="note_required"):
        await pause(e.factory, fake, source.source_id, e.user_id, reason="  ")
    assert e.fake.toggles == []

    await pause(e.factory, fake, source.source_id, e.user_id, reason=REASON)
    with pytest.raises(RegisterError, match="not_ingested"):
        await pause(e.factory, fake, source.source_id, e.user_id, reason=REASON)
    with pytest.raises(RegisterError, match="not_proposed"):
        await approve(e.factory, source.source_id, e.user_id)  # paused -> approved
    with pytest.raises(RegisterError, match="not_failed"):
        await retry(e.factory, source.source_id, e.user_id)
    assert (await source_row(admin_conn, source.source_id))["status"] == "paused"


async def test_the_register_refuses_a_pause_without_its_record(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    _, run = env
    source = await two_datasets(run)
    for values in (
        "status = 'paused'",  # no date, reviewer or reason
        "status = 'paused', paused_at = now(), paused_by = gen_random_uuid(), pause_reason = ' '",
        "paused_at = now()",  # pause fields on an ingested row
    ):
        with pytest.raises(asyncpg.CheckViolationError):
            await admin_conn.execute(f"UPDATE sources SET {values} WHERE id = $1", source.source_id)


async def test_a_failed_toggle_on_the_second_dataset_reenables_the_first(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source = await two_datasets(run)
    first, second = sorted(source.document_ids)
    e.fake.fail_toggle[second] = RagflowError("set_document_enabled", 102)

    with pytest.raises(RegisterError) as refused:
        await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert refused.value.code == "ragflow_102"
    document = source.document_ids[first]
    assert e.fake.toggles == [(first, document, 0), (first, document, 1)]
    assert enabled(e.fake, source) == [True, True]
    row = await source_row(admin_conn, source.source_id)
    assert (row["status"], row["paused_at"], row["paused_by"], row["pause_reason"]) == (
        "ingested",
        None,
        None,
        None,
    )
    trail = await events(admin_conn, source.source_id)
    names = [name for name, _ in trail]
    assert "source.paused" not in names
    failed = dict(trail)["source.pause_failed"]
    assert (failed["error_code"], failed["outcome"], failed["after"]) == (
        "ragflow_102",
        "undone",
        {"status": "ingested"},
    )

    # A toggle that answers success with the old status counts as a failure too.
    e.fake.fail_toggle.clear()
    e.fake.toggles.clear()
    e.fake.stale_status.add(second)
    with pytest.raises(RegisterError, match="ragflow_status_mismatch"):
        await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert enabled(e.fake, source) == [True, True]
    assert (await source_row(admin_conn, source.source_id))["status"] == "ingested"


async def test_an_undo_that_fails_is_reported_and_the_row_stays_ingested(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source = await two_datasets(run)
    first, second = sorted(source.document_ids)
    e.fake.fail_toggle[second] = RagflowError("set_document_enabled", 500)
    e.fake.fail_enable[first] = RagflowError("set_document_enabled", 500)

    with pytest.raises(RegisterError, match="pause_undo_failed"):
        await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert (await source_row(admin_conn, source.source_id))["status"] == "ingested"
    failed = dict(await events(admin_conn, source.source_id))["source.pause_failed"]
    assert failed["outcome"] == "undo_failed"
    # RAGFlow now disagrees with the register, and datasets sync says so.
    async with e.factory() as session:
        found = await status_mismatches(session, e.fake)  # type: ignore[arg-type]
    tag = {dataset_id: tag for tag, dataset_id in e.datasets.items()}[first]
    assert found == [StatusMismatch(source.source_id, tag, first, "enabled", "disabled")]


async def test_the_toggle_never_sends_a_boolean_or_a_status_field(
    env: tuple[Env, Ingest], capsys: pytest.CaptureFixture[str]
) -> None:
    e, run = env
    source = await two_datasets(run)
    async with RagflowClient(
        "http://ragflow:9380", "test-key", 5, transport=e.fake.transport()
    ) as client:
        await pause(e.factory, client, source.source_id, e.user_id, reason=REASON)
        await resume(e.factory, client, source.source_id, e.user_id)
    assert e.fake.patch_payloads == [{"enabled": 0}] * 2 + [{"enabled": 1}] * 2
    for payload in e.fake.patch_payloads:
        assert type(payload["enabled"]) is int and "status" not in payload
    assert enabled(e.fake, source) == [True, True]
    # The response names the file; the log carries the code, status and latency only.
    out = capsys.readouterr().out
    assert "ragflow.set_document_enabled" in out
    assert "tidewater" not in out.lower() and REASON not in out

    # What the fake does with the payloads the client must never send, as RAGFlow does.
    document_id = next(iter(source.document_ids.values()))
    dataset_id = next(iter(source.document_ids))
    refused = e.fake.patch_document(dataset_id, document_id, {"enabled": False})
    assert refused["code"] == 102
    ignored = e.fake.patch_document(dataset_id, document_id, {"status": "0"})
    assert (ignored["code"], ignored["data"]["status"]) == (0, "1")


# The pause.


async def test_a_paused_source_is_not_retrieved_and_comes_back_on_resume_without_a_parse(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source = await two_datasets(run)
    other = await run(
        SourceFile("other.md", "markdown", b"# Synthetic other page"),
        linked("sample-reports", "https://example.org/other"),
    )
    client_tenant, _ = await other_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-reports'] WHERE tenant_id = $1",
        client_tenant,
    )
    assert await retrievable(e.fake, e.factory, client_tenant, source) == 3
    parsed, documents = list(e.fake.parsed), dict(source.document_ids)

    paused = await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    assert (paused.status, paused.documents) == ("paused", 2)
    assert await retrievable(e.fake, e.factory, client_tenant, source) == 0
    assert await retrievable(e.fake, e.factory, client_tenant, other) == 3  # others stay
    row = await source_row(admin_conn, source.source_id)
    assert (row["status"], row["paused_by"], row["pause_reason"]) == ("paused", e.user_id, REASON)
    assert row["paused_at"] is not None
    assert json.loads(row["ragflow_document_ids"]) == documents  # left in place

    resumed = await resume(e.factory, e.fake, source.source_id, e.user_id)  # type: ignore[arg-type]
    assert resumed.status == "ingested"
    assert await retrievable(e.fake, e.factory, client_tenant, source) == 3
    assert e.fake.parsed == parsed and e.fake.deleted == []  # no re-parse, nothing deleted
    row = await source_row(admin_conn, source.source_id)
    assert (row["status"], row["paused_at"], row["paused_by"], row["pause_reason"]) == (
        "ingested",
        None,
        None,
        None,
    )
    assert json.loads(row["ragflow_document_ids"]) == documents
    assert row["chunk_count"] == 6

    trail = await events(admin_conn, source.source_id)
    by_name = dict(trail)
    assert by_name["source.paused"] | {"roles": None} == {
        "source_id": str(source.source_id),
        "before": {"status": "ingested"},
        "after": {"status": "paused"},
        "roles": None,
        "outcome": "ok",
        "count": 2,
    }
    assert by_name["source.paused"]["roles"] == ["content_editor", "content_reviewer"]
    assert (by_name["source.resumed"]["before"], by_name["source.resumed"]["after"]) == (
        {"status": "paused"},
        {"status": "ingested"},
    )
    assert REASON not in json.dumps(trail)  # the reason stays on the row
    async with e.factory() as session:
        assert await status_mismatches(session, e.fake) == []  # type: ignore[arg-type]


async def test_the_cache_key_changes_and_cited_answers_are_purged_on_pause(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    e, run = env
    source = await two_datasets(run)
    other = await run(
        SourceFile("other.md", "markdown", b"# Synthetic other page"),
        linked("sample-reports", "https://example.org/other"),
    )
    client_tenant, _ = await other_tenant(admin_conn)
    sid, oid = str(source.source_id), str(other.source_id)
    await cache.set(client_tenant, "answer:corpus_only:a", cached([sid], [sid]), 60)
    await cache.set(client_tenant, "answer:corpus_only:b", cached([oid], [oid]), 60)
    await cache.set(INTERNAL_TENANT_ID, "answer:corpus_only:c", cached(None, [sid]), 60)

    async def version() -> str:
        async with tenant_session(e.factory, client_tenant) as session:
            return (await resolve_package(session, ("sample-reports",))).corpus_version

    before = await version()
    paused = await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    during = await version()
    await resume(e.factory, e.fake, source.source_id, e.user_id)  # type: ignore[arg-type]
    after = await version()
    assert before != during and during != after
    assert paused.cache_entries_purged == 2
    assert sorted(k.rsplit(":", 1)[-1] for k in redis.store) == ["b"]


async def test_a_paused_source_stays_on_the_takedown_queue_and_can_be_withdrawn(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source = await two_datasets(run)
    due = await record_takedown(
        e.factory,
        source.source_id,
        e.user_id,
        reference="TD-1 (synthetic)",
        requested_on=date(2026, 10, 26),
        licence_breach=False,
    )
    await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    async with e.factory() as session:
        queue = await takedown_queue(session)
    assert [(i.source_id, i.status, i.due_on) for i in queue] == [(source.source_id, "paused", due)]
    await request_withdrawal(e.factory, source.source_id, e.user_id, reason="takedown")
    await run_queue(e)
    row = await source_row(admin_conn, source.source_id)
    assert (row["status"], row["paused_at"], row["pause_reason"]) == ("withdrawn", None, None)
    assert set(source.document_ids.values()) <= set(e.fake.deleted)
    async with e.factory() as session:
        assert await takedown_queue(session) == []


async def test_datasets_sync_reports_a_document_status_that_disagrees(
    env: tuple[Env, Ingest],
) -> None:
    e, run = env
    source = await two_datasets(run)
    await pause(e.factory, e.fake, source.source_id, e.user_id, reason=REASON)  # type: ignore[arg-type]
    first, second = sorted(source.document_ids)
    # Someone enables one document by hand in RAGFlow and deletes the other.
    document = source.document_ids[first]
    e.fake.documents[document] = replace(e.fake.documents[document], enabled=True)
    del e.fake.documents[source.document_ids[second]]
    tags = {dataset_id: tag for tag, dataset_id in e.datasets.items()}
    async with e.factory() as session:
        found = await status_mismatches(session, e.fake)  # type: ignore[arg-type]
    assert found == [
        StatusMismatch(source.source_id, tags[first], first, "disabled", "enabled"),
        StatusMismatch(source.source_id, tags[second], second, "disabled", "missing"),
    ]


def test_the_toggle_lives_in_the_register_not_in_a_job() -> None:
    """P2A-01: the RAGFlow toggle is made inside the register action."""
    assert "set_document_enabled" not in inspect.getsource(worker)
    assert "set_enabled_everywhere" in inspect.getsource(register)


# P2A-04: the CLI, the console's code path.


def test_cli_pause_and_resume_flags() -> None:
    source = str(UUID(int=9))
    args = cli.build_parser().parse_args(
        ["sources", "pause", source, "--as", "r@example.org", "--reason", "rights check"]
    )
    assert (args.sources_command, str(args.source_id), args.reviewer, args.reason) == (
        "pause",
        source,
        "r@example.org",
        "rights check",
    )
    args = cli.build_parser().parse_args(["sources", "resume", source, "--as", "r@example.org"])
    assert (args.sources_command, args.reviewer) == ("resume", "r@example.org")
    for missing in (
        ["sources", "pause", source, "--as", "r@example.org"],  # no reason
        ["sources", "pause", source, "--reason", "r"],  # no reviewer
        ["sources", "resume", source],
    ):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(missing)


async def test_cli_pauses_and_resumes_through_the_register(
    env: tuple[Env, Ingest],
    redis: FakeRedis,
    database: MigratedDatabase,
    admin_conn: asyncpg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    e, run = env
    source = await two_datasets(run)
    sid = str(source.source_id)
    # The test database's password is the CI one, which the startup check refuses (as it
    # should); load the test settings, then point them at the test database.
    settings = load_settings(environ=ENV)
    secrets = replace(settings.secrets, database_url=SecretStr(database.sqlalchemy_url))
    settings = replace(settings, secrets=secrets)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    class Client:
        async def __aenter__(self) -> FakeRagflow:
            return e.fake

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(cli.RagflowClient, "from_settings", staticmethod(lambda _: Client()))
    # The CLI connects the answer cache for a pause; here it is the test's fake Redis.
    connected: list[str] = []

    async def keep_open() -> None:
        return None

    monkeypatch.setattr(cli.cache, "connect", connected.append)
    monkeypatch.setattr(cli.cache, "close", keep_open)
    await cache.set(INTERNAL_TENANT_ID, "answer:corpus_only:a", cached([sid], [sid]), 60)
    reviewer = "editor@example.org"

    def parsed(*argv: str) -> Any:
        return cli.build_parser().parse_args(["sources", *argv])

    # Refused first: an editor without the reviewer role, then a resume of an ingested row.
    await content_user(admin_conn, "content_editor")
    assert await cli._sources(parsed("pause", sid, "--as", reviewer, "--reason", REASON)) == 1
    await content_user(admin_conn, "content_editor", "content_reviewer")
    assert await cli._sources(parsed("resume", sid, "--as", reviewer)) == 1
    assert e.fake.toggles == []

    assert await cli._sources(parsed("pause", sid, "--as", reviewer, "--reason", REASON)) == 0
    assert (await source_row(admin_conn, source.source_id))["status"] == "paused"
    assert enabled(e.fake, source) == [False, False]
    assert await cli._sources(parsed("resume", sid, "--as", reviewer)) == 0
    assert (await source_row(admin_conn, source.source_id))["status"] == "ingested"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    mine = [line for line in lines if line["event"] in ("sources.pause", "sources.resume")]
    assert [(line["event"], line["status"], line.get("error_code")) for line in mine] == [
        ("sources.pause", "refused", "not_content_reviewer"),
        ("sources.resume", "refused", "not_paused"),
        ("sources.pause", "paused", None),
        ("sources.resume", "ingested", None),
    ]
    assert mine[2]["count"] == 2
    assert redis.store == {} and len(connected) == 2  # purged on pause; connected per pause
    assert REASON not in json.dumps(lines)
