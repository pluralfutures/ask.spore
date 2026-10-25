"""P0-08: ``ask-spore datasets sync`` against a fake RAGFlow and the test database."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.content.datasets import StatusMismatch, SyncResult, sync_datasets
from app.content.tags import TagConfig, load_tags
from app.core.config import DEFAULT_CONFIG_DIR, load_settings
from app.core.db import create_engine, session_factory
from tests.conftest import MigratedDatabase
from tests.ragflow_fake import FakeRagflow

EMBEDDING = "BAAI/bge-m3@Builtin"
ENV = {
    "MISTRAL_API_KEY": "test-mistral-key",
    "SCALEWAY_API_KEY": "test-scaleway-key",
    "RAGFLOW_API_KEY": "test-ragflow-key",
    "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:1/none",  # never connected
    "REDIS_URL": "redis://localhost:6379/0",
    "PHASE0_BEARER_TOKEN": "test-bearer-token-0123456789abcdef",
    "AUTHENTIK_CLIENT_SECRET": "test-authentik-client-secret",
    "AUTHENTIK_API_TOKEN": "test-authentik-api-token",
}
TAGS = load_tags(DEFAULT_CONFIG_DIR)

Sync = Callable[..., Awaitable[list[SyncResult]]]


@pytest.fixture
async def sync(database: MigratedDatabase, admin_conn: asyncpg.Connection) -> AsyncIterator[Sync]:
    """Run one sync in its own committed transaction, as the application role."""
    await admin_conn.execute("DELETE FROM datasets")
    engine = create_engine(database.sqlalchemy_url)
    factory = session_factory(engine)

    async def run(
        fake: FakeRagflow, tags: dict[str, TagConfig] = TAGS, embedding: str = EMBEDDING
    ) -> list[SyncResult]:
        session: AsyncSession
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL ROLE askspore_app"))
            return await sync_datasets(session, fake, tags, embedding)  # type: ignore[arg-type]

    yield run
    await engine.dispose()
    await admin_conn.execute("DELETE FROM datasets")


async def mapping(admin_conn: asyncpg.Connection) -> dict[str, str]:
    rows = await admin_conn.fetch("SELECT tag, ragflow_dataset_id FROM datasets")
    return {row["tag"]: row["ragflow_dataset_id"] for row in rows}


def statuses(results: list[SyncResult]) -> dict[str, str]:
    return {r.tag: r.status for r in results}


async def test_creates_one_dataset_per_tag_with_its_chunk_method(
    sync: Sync, admin_conn: asyncpg.Connection
) -> None:
    fake = FakeRagflow()
    results = await sync(fake)

    assert statuses(results) == dict.fromkeys(TAGS, "created")
    assert sorted(fake.created) == [
        "ask-spore-cc-shared",
        "ask-spore-cc-team1-healthcare-gpo",
        "ask-spore-cc-team2-college-universities",
        "ask-spore-cc-team3-commercial-restaurants",
        "ask-spore-sample-analysis",
        "ask-spore-sample-reports",
        "ask-spore-sample-web",
    ]
    by_name = {d.name: d for d in fake.datasets.values()}
    assert by_name["ask-spore-sample-reports"].chunk_method == "paper"
    assert by_name["ask-spore-sample-analysis"].chunk_method == "naive"
    assert by_name["ask-spore-sample-web"].chunk_method == "naive"
    assert {d.embedding_model for d in fake.datasets.values()} == {EMBEDDING}
    assert await mapping(admin_conn) == {tag: by_name[f"ask-spore-{tag}"].id for tag in TAGS}


async def test_new_tags_get_datasets_on_the_next_run(
    sync: Sync, admin_conn: asyncpg.Connection
) -> None:
    # P1a-04 (findings E1): an instance synced before the client tags existed creates
    # exactly their four datasets on its next run and leaves the earlier ones alone.
    client = {tag for tag in TAGS if tag.startswith("cc-")}
    assert len(client) == 4
    fake = FakeRagflow()
    await sync(fake, {tag: config for tag, config in TAGS.items() if tag not in client})
    before = await mapping(admin_conn)
    created = len(fake.created)

    results = await sync(fake)

    assert {tag for tag, status in statuses(results).items() if status == "created"} == client
    assert sorted(fake.created[created:]) == sorted(f"ask-spore-{tag}" for tag in client)
    by_name = {d.name: d for d in fake.datasets.values()}
    assert {by_name[f"ask-spore-{tag}"].chunk_method for tag in client} == {"paper"}
    after = await mapping(admin_conn)
    assert {tag: after[tag] for tag in before} == before and set(after) == set(TAGS)


async def test_second_run_is_a_no_op(sync: Sync, admin_conn: asyncpg.Connection) -> None:
    fake = FakeRagflow()
    await sync(fake)
    before = await mapping(admin_conn)
    created = list(fake.created)

    results = await sync(fake)

    assert statuses(results) == dict.fromkeys(TAGS, "ok")
    assert fake.created == created
    assert await mapping(admin_conn) == before


async def test_adopts_existing_dataset_by_exact_name(
    sync: Sync, admin_conn: asyncpg.Connection
) -> None:
    fake = FakeRagflow()
    existing = fake.add_dataset("ask-spore-sample-web", "naive")
    # A near miss RAGFlow itself produced must not be adopted.
    fake.add_dataset("ask-spore-sample-reports(1)", "paper")

    results = await sync(fake)

    assert statuses(results)["sample-web"] == "adopted"
    assert statuses(results)["sample-reports"] == "created"
    assert (await mapping(admin_conn))["sample-web"] == existing.id
    assert "ask-spore-sample-web(1)" not in {d.name for d in fake.datasets.values()}


async def test_mismatched_dataset_is_reported_not_changed(
    sync: Sync, admin_conn: asyncpg.Connection
) -> None:
    fake = FakeRagflow()
    fake.add_dataset("ask-spore-sample-reports", "naive")  # config says paper

    results = await sync(fake)

    failed = [r for r in results if r.failed]
    assert [(r.tag, r.status) for r in failed] == [("sample-reports", "mismatch")]
    assert "sample-reports" not in await mapping(admin_conn)


async def test_wrong_embedding_model_is_a_mismatch(sync: Sync) -> None:
    fake = FakeRagflow()
    await sync(fake)
    results = await sync(fake, embedding="BAAI/bge-small-en-v1.5@Builtin")
    assert statuses(results) == dict.fromkeys(TAGS, "mismatch")


async def test_dataset_deleted_in_ragflow_is_reported_missing_not_recreated(
    sync: Sync, admin_conn: asyncpg.Connection
) -> None:
    fake = FakeRagflow()
    await sync(fake)
    web_id = (await mapping(admin_conn))["sample-web"]
    del fake.datasets[web_id]
    created = list(fake.created)

    results = await sync(fake)

    assert statuses(results)["sample-web"] == "missing"
    assert fake.created == created
    assert (await mapping(admin_conn))["sample-web"] == web_id


async def test_duplicate_names_in_ragflow_are_ambiguous(sync: Sync) -> None:
    fake = FakeRagflow()
    first = fake.add_dataset("ask-spore-sample-web", "naive")
    second = fake.add_dataset("x", "naive")
    fake.datasets[second.id] = second.__class__(**{**second.__dict__, "name": first.name})
    results = await sync(fake)
    assert statuses(results)["sample-web"] == "ambiguous"


async def test_mapped_tag_removed_from_config_is_reported(sync: Sync) -> None:
    fake = FakeRagflow()
    await sync(fake)
    remaining = {tag: cfg for tag, cfg in TAGS.items() if tag != "sample-web"}
    results = await sync(fake, tags=remaining)
    assert statuses(results)["sample-web"] == "unconfigured"
    assert not any(r.failed for r in results)


def test_cli_logs_metadata_and_exits_non_zero_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = [
        SyncResult("sample-reports", "created", "a" * 32),
        SyncResult("sample-web", "mismatch", "b" * 32),
    ]

    async def fake_sync(*_: Any) -> list[SyncResult]:
        return results

    mismatches: list[StatusMismatch] = []

    async def fake_mismatches(*_: Any) -> list[StatusMismatch]:
        return mismatches

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def begin(self) -> Session:
            return self

    monkeypatch.setattr(cli, "get_settings", lambda: load_settings(environ=ENV))
    monkeypatch.setattr(cli, "sync_datasets", fake_sync)
    monkeypatch.setattr(cli, "status_mismatches", fake_mismatches)
    monkeypatch.setattr(cli.RagflowClient, "from_settings", staticmethod(lambda _: Client()))
    monkeypatch.setattr(cli, "session_factory", lambda _: Session)

    assert cli.main(["datasets", "sync"]) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["tag"], line["status"], line["level"]) for line in lines] == [
        ("sample-reports", "created", "info"),
        ("sample-web", "mismatch", "error"),
    ]
    assert all(line["event"] == "datasets.sync" for line in lines)

    # P2A-01: a document whose RAGFlow status disagrees with the register fails the run.
    results[1] = SyncResult("sample-web", "ok", "b" * 32)
    source_id = uuid.uuid4()
    mismatches.append(StatusMismatch(source_id, "sample-web", "b" * 32, "disabled", "enabled"))
    assert cli.main(["datasets", "sync"]) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1] == lines[-1] | {
        "event": "datasets.status_mismatch",
        "level": "error",
        "source_id": str(source_id),
        "tag": "sample-web",
        "status": "expected_disabled_found_enabled",
    }
    mismatches.clear()
    assert cli.main(["datasets", "sync"]) == 0


def test_cli_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli.main(["datasets"])


async def test_counts_report_ragflows_figures_per_mapped_tag(
    sync: Sync, database: MigratedDatabase, admin_conn: asyncpg.Connection
) -> None:
    """P1c-10: the deploy script's dataset check, metadata only."""
    from dataclasses import replace

    from app.content.datasets import dataset_counts

    fake = FakeRagflow()
    await sync(fake)
    ids = await mapping(admin_conn)
    reports = ids["sample-reports"]
    fake.datasets[reports] = replace(fake.datasets[reports], document_count=59, chunk_count=2580)
    del fake.datasets[ids["sample-web"]]  # mapped, but gone from RAGFlow
    engine = create_engine(database.sqlalchemy_url)
    try:
        async with session_factory(engine)() as session, session.begin():
            await session.execute(text("SET LOCAL ROLE askspore_app"))
            counts = {c.tag: c for c in await dataset_counts(session, fake)}  # type: ignore[arg-type]
    finally:
        await engine.dispose()
    assert set(counts) == set(TAGS)
    assert (counts["sample-reports"].documents, counts["sample-reports"].chunks) == (59, 2580)
    assert (counts["cc-shared"].documents, counts["cc-shared"].chunks) == (0, 0)
    assert counts["sample-web"].documents is None
