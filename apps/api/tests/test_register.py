"""P1b-01: source register states, content roles and audited transitions."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from app import cli
from app.content.ingest import SourceMetadata, ingest_source, load_path
from app.content.register import RegisterError, approve, propose, reject, retry
from app.content.roles import RoleError, grant_role, revoke_role, user_by_email
from app.content.store import store_licence
from app.core.db import create_engine, session_factory
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase, _admin_dsn, _execute, _with_database, migrate
from tests.test_ingest import DOCX, PDF, TAGS, Env, Ingest, content_user, env, meta, source_row

__all__ = ["env"]  # the fixture, imported for its use here


async def events(admin_conn: asyncpg.Connection, source_id: UUID) -> list[dict[str, Any]]:
    rows = await admin_conn.fetch(
        "SELECT event, actor_user_id, tenant_id, metadata FROM audit_events "
        "WHERE metadata->>'source_id' = $1 ORDER BY created_at, id",
        str(source_id),
    )
    return [
        {
            "event": r["event"],
            "actor": r["actor_user_id"],
            "tenant_id": r["tenant_id"],
            **json.loads(r["metadata"]),
        }
        for r in rows
    ]


@pytest.fixture
async def analyst(admin_conn: asyncpg.Connection) -> AsyncIterator[UUID]:
    """A second internal user, a reviewer only."""
    user_id: UUID = await admin_conn.fetchval(
        "SELECT id FROM users WHERE tenant_id = $1 AND email = 'analyst@example.org'",
        INTERNAL_TENANT_ID,
    )
    await admin_conn.execute(
        "INSERT INTO content_roles (user_id, role) VALUES ($1, 'content_reviewer') "
        "ON CONFLICT DO NOTHING",
        user_id,
    )
    yield user_id
    await admin_conn.execute("DELETE FROM content_roles WHERE user_id = $1", user_id)


async def proposal(e: Env, path: Path = PDF, proposer: UUID | None = None) -> UUID:
    submission = await propose(
        e.factory,
        TAGS,
        load_path(path),
        meta("sample-reports"),
        content_root=e.content_root,
        proposer_id=e.user_id if proposer is None else proposer,
    )
    assert (submission.outcome, submission.status) == ("proposed", "proposed")
    return submission.source_id


async def test_proposal_is_recorded_and_staged_but_reaches_no_dataset(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    row = await source_row(admin_conn, source_id)
    assert (row["status"], row["proposed_by"], row["approved_by"]) == ("proposed", e.user_id, None)
    assert e.fake.uploads == [] and e.fake.parsed == []
    [event] = await events(admin_conn, source_id)
    assert event["event"] == "source.proposed"
    assert (event["actor"], event["tenant_id"]) == (e.user_id, INTERNAL_TENANT_ID)
    assert (event["before"], event["after"]) == ({}, {"status": "proposed"})


async def test_a_proposal_waiting_for_review_is_not_proposed_twice(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    source_id = await proposal(e)
    again = await propose(
        e.factory,
        TAGS,
        load_path(PDF),
        meta("sample-reports"),
        content_root=e.content_root,
        proposer_id=None,
    )
    assert (again.source_id, again.outcome, again.status) == (source_id, "pending", "proposed")
    assert await admin_conn.fetchval("SELECT count(*) FROM sources") == 1
    # Without a reviewer the CLI path leaves it proposed and uploads nothing.
    result = await run(load_path(PDF), meta("sample-reports"), reviewer_id=None)
    assert (result.source_id, result.status) == (source_id, "proposed")
    assert e.fake.uploads == []


async def test_proposing_needs_the_editor_role(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    await content_user(admin_conn, "content_reviewer")
    with pytest.raises(RoleError) as refused:
        await proposal(e)
    assert refused.value.code == "not_content_editor"
    assert await admin_conn.fetchval("SELECT count(*) FROM sources") == 0


async def test_an_editor_cannot_approve(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    await content_user(admin_conn, "content_editor")
    with pytest.raises(RoleError) as refused:
        await approve(e.factory, source_id, e.user_id)
    assert refused.value.code == "not_content_reviewer"
    with pytest.raises(RoleError):
        await reject(e.factory, source_id, e.user_id, note="no")
    assert (await source_row(admin_conn, source_id))["status"] == "proposed"
    assert [x["event"] for x in await events(admin_conn, source_id)] == ["source.proposed"]


async def test_self_approval_is_allowed_and_audited_with_both_roles(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    await approve(e.factory, source_id, e.user_id, note="our own corpus")
    row = await source_row(admin_conn, source_id)
    assert (row["status"], row["approved_by"]) == ("approved", e.user_id)
    assert row["approved_at"] is not None
    assert row["review_note"] == "our own corpus"
    approval = (await events(admin_conn, source_id))[-1]
    assert approval["event"] == "source.approved"
    assert approval["actor"] == e.user_id
    assert (approval["before"], approval["after"]) == (
        {"status": "proposed"},
        {"status": "approved"},
    )
    assert approval["roles"] == ["content_editor", "content_reviewer"]
    assert approval["self_approval"] is True
    assert "our own corpus" not in json.dumps(approval, default=str)  # the note stays on the row
    assert e.fake.uploads == []  # approval alone uploads nothing


async def test_approval_by_another_reviewer_is_not_self_approval(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, analyst: UUID
) -> None:
    e, _ = env
    source_id = await proposal(e)
    await approve(e.factory, source_id, analyst)
    approval = (await events(admin_conn, source_id))[-1]
    assert (approval["actor"], approval["roles"], approval["self_approval"]) == (
        analyst,
        ["content_reviewer"],
        False,
    )


async def test_reject_needs_a_note_and_ends_the_proposal(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    with pytest.raises(RegisterError) as refused:
        await reject(e.factory, source_id, e.user_id, note="  ")
    assert refused.value.code == "note_required"
    await reject(e.factory, source_id, e.user_id, note="licence unclear")
    row = await source_row(admin_conn, source_id)
    assert (row["status"], row["review_note"], row["approved_at"]) == (
        "rejected",
        "licence unclear",
        None,
    )
    with pytest.raises(RegisterError) as refused:
        await approve(e.factory, source_id, e.user_id)
    assert refused.value.code == "not_proposed"
    assert [x["event"] for x in await events(admin_conn, source_id)] == [
        "source.proposed",
        "source.rejected",
    ]


async def test_ingestion_refuses_a_source_that_is_not_approved(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    for status in ("proposed", "rejected", "failed"):
        await admin_conn.execute(
            "UPDATE sources SET status = $2, approved_at = now() WHERE id = $1", source_id, status
        )
        result = await ingest_source(
            e.factory,
            e.fake,  # type: ignore[arg-type]
            TAGS,
            source_id,
            content_root=e.content_root,
        )
        assert (result.status, result.error_code) == ("refused", "not_approved")
        assert (await source_row(admin_conn, source_id))["status"] == status
    assert e.fake.uploads == []
    unknown = await ingest_source(
        e.factory,
        e.fake,  # type: ignore[arg-type]
        TAGS,
        uuid.uuid4(),
        content_root=e.content_root,
    )
    assert (unknown.status, unknown.error_code) == ("refused", "no_source")


async def test_every_transition_is_audited_with_before_and_after(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    from tests.ragflow_fake import Outcome

    e.fake.outcomes[".pdf"] = Outcome(run="FAIL", chunk_count=0)
    failed = await run(load_path(PDF), meta("sample-reports"))
    assert failed.status == "failed"
    e.fake.outcomes[".pdf"] = Outcome()
    await retry(e.factory, failed.source_id, e.user_id)
    result = await ingest_source(
        e.factory,
        e.fake,  # type: ignore[arg-type]
        TAGS,
        failed.source_id,
        content_root=e.content_root,
    )
    assert result.status == "ingested"
    trail = [
        (x["event"], x["before"], x["after"], x.get("error_code"))
        for x in await events(admin_conn, failed.source_id)
    ]
    assert trail == [
        ("source.proposed", {}, {"status": "proposed"}, None),
        ("source.approved", {"status": "proposed"}, {"status": "approved"}, None),
        ("source.failed", {"status": "approved"}, {"status": "failed"}, "parse_failed"),
        ("source.retried", {"status": "failed"}, {"status": "approved"}, None),
        ("source.ingested", {"status": "approved"}, {"status": "ingested"}, None),
    ]
    row = await source_row(admin_conn, failed.source_id)
    assert (row["status"], row["error"]) == ("ingested", None)
    # Metadata only: no title, publisher or document IDs in the trail.
    text = json.dumps(await events(admin_conn, failed.source_id), default=str)
    for value in ("Tidewater", "Fictional", *result.document_ids.values()):
        assert value not in text


async def test_a_taken_down_file_is_not_proposed_again(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(PDF), meta("sample-reports"))
    await admin_conn.execute(
        "UPDATE sources SET status = 'withdrawn', withdrawn_at = now(), "
        "withdrawal_reason = 'takedown', takedown_reference = 'TD-1' WHERE id = $1",
        first.source_id,
    )
    uploads = len(e.fake.uploads)
    again = await run(load_path(PDF), meta("sample-reports"))
    assert (again.source_id, again.status, again.error_code) == (
        first.source_id,
        "failed",
        "taken_down",
    )
    assert await admin_conn.fetchval("SELECT count(*) FROM sources") == 1
    assert len(e.fake.uploads) == uploads


async def test_retag_waits_for_a_reviewer(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, run = env
    first = await run(load_path(DOCX), meta("sample-reports"))
    uploads = len(e.fake.uploads)
    pending = await run(load_path(DOCX), meta("sample-reports", "sample-web"), reviewer_id=None)
    assert (pending.source_id, pending.status) == (first.source_id, "retag_pending")
    assert len(e.fake.uploads) == uploads
    assert (await source_row(admin_conn, first.source_id))["tags"] == ["sample-reports"]
    retagged = await run(load_path(DOCX), meta("sample-reports", "sample-web"))
    assert retagged.status == "retagged"
    approval = [x for x in await events(admin_conn, first.source_id) if "retag" in x["event"]]
    assert [x["event"] for x in approval] == ["source.retag_approved", "ingest.source_retagged"]
    assert approval[0]["actor"] == e.user_id


async def test_status_and_record_constraints(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    source_id = await proposal(e)
    for sql in (
        "UPDATE sources SET status = 'registered' WHERE id = $1",
        "UPDATE sources SET status = 'ingesting' WHERE id = $1",
        "UPDATE sources SET status = 'approved' WHERE id = $1",  # no approved_at
        "UPDATE sources SET status = 'withdrawn', approved_at = now() WHERE id = $1",  # no reason
        "UPDATE sources SET status = 'withdrawn', approved_at = now(), withdrawn_at = now() "
        "WHERE id = $1",  # a date but no reason
        "UPDATE sources SET licence_file_path = '../letter.pdf' WHERE id = $1",
    ):
        with pytest.raises(asyncpg.CheckViolationError):
            await admin_conn.execute(sql, source_id)
    path = store_licence(e.content_root, b"synthetic permission letter", ".PDF")
    assert path.startswith("licences/") and path.endswith(".pdf")
    await admin_conn.execute(
        "UPDATE sources SET licence_file_path = $2 WHERE id = $1", source_id, path
    )
    assert (e.content_root / path).read_bytes() == b"synthetic permission letter"


async def test_roles_are_internal_only_and_read_only_for_the_app(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    other_tenant = uuid.uuid4()
    await admin_conn.execute(
        "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Other')",
        other_tenant,
        f"o-{other_tenant.hex}",
    )
    client_user = await admin_conn.fetchval(
        "INSERT INTO users (tenant_id, email, display_name) VALUES ($1, $2, 'Client') RETURNING id",
        other_tenant,
        f"client-{other_tenant.hex[:8]}@example.com",
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await admin_conn.execute(
            "INSERT INTO content_roles (tenant_id, user_id, role) "
            "VALUES ($1, $2, 'content_reviewer')",
            other_tenant,
            client_user,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await admin_conn.execute(
            "INSERT INTO content_roles (user_id, role) VALUES ($1, 'operator')", env[0].user_id
        )
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(INTERNAL_TENANT_ID))
    assert await app_conn.fetchval("SELECT count(*) FROM content_roles") > 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute(
            "INSERT INTO content_roles (user_id, role) VALUES ($1, 'content_reviewer')",
            client_user,
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM content_roles")


async def test_grant_and_revoke_are_audited(
    env: tuple[Env, Ingest], database: MigratedDatabase, admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    await content_user(admin_conn)  # no roles
    engine = create_engine(database.sqlalchemy_url)  # as the owner, like the CLI
    try:
        owner = session_factory(engine)
        assert await grant_role(owner, email="Editor@Example.org", role="content_editor") == (
            "granted"
        )
        assert await grant_role(owner, email="editor@example.org", role="content_editor") == (
            "already_granted"
        )
        assert await grant_role(owner, email="nobody@example.org", role="content_editor") == (
            "no_user"
        )
        assert await user_by_email(owner, "editor@example.org") == e.user_id
        with pytest.raises(RoleError):
            await user_by_email(owner, "nobody@example.org")
        assert await revoke_role(owner, email="editor@example.org", role="content_editor") == (
            "revoked"
        )
        assert await revoke_role(owner, email="editor@example.org", role="content_editor") == (
            "not_granted"
        )
    finally:
        await engine.dispose()
    rows = await admin_conn.fetch(
        "SELECT event, metadata FROM audit_events WHERE event LIKE 'content_role.%' "
        "AND metadata::text LIKE $1 ORDER BY created_at",
        f"%{e.user_id}%",
    )
    assert [(r["event"], json.loads(r["metadata"])) for r in rows][-2:] == [
        (
            "content_role.granted",
            {"before": {}, "after": {"user_id": str(e.user_id), "role": "content_editor"}},
        ),
        (
            "content_role.revoked",
            {"before": {"user_id": str(e.user_id), "role": "content_editor"}, "after": {}},
        ),
    ]


def test_cli_flags() -> None:
    args = cli.build_parser().parse_args(
        ["ingest-manifest", "m.csv", "--approve-as", "owner@example.org"]
    )
    assert (args.approve_as, args.propose_as) == ("owner@example.org", None)
    args = cli.build_parser().parse_args(
        ["sources", "reject", str(uuid.UUID(int=1)), "--as", "r@example.org", "--note", "no"]
    )
    assert (args.sources_command, args.source_id, args.note) == ("reject", uuid.UUID(int=1), "no")
    with pytest.raises(SystemExit):  # a rejection needs a note
        cli.build_parser().parse_args(["sources", "reject", str(uuid.UUID(int=1)), "--as", "r"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["content-roles", "grant", "--email", "a@example.org", "--role", "operator"]
        )


def test_migration_maps_phase0_statuses() -> None:
    admin = _admin_dsn()
    if admin is None:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set")
    name = f"askspore_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_execute(admin, f'CREATE DATABASE "{name}"'))
    db = MigratedDatabase(dsn=_with_database(admin, name))
    try:
        migrate(db, "0012")

        async def arrange() -> None:
            conn = await asyncpg.connect(db.dsn)
            try:
                for status in ("registered", "ingesting", "ingested", "withdrawn"):
                    await conn.execute(
                        "INSERT INTO sources (type, title, publisher, licence_basis, status) "
                        "VALUES ('pdf', $1, 'P', 'x', $1)",
                        status,
                    )
            finally:
                await conn.close()

        async def check() -> dict[str, tuple[Any, ...]]:
            conn = await asyncpg.connect(db.dsn)
            try:
                rows = await conn.fetch(
                    "SELECT title, status, approved_at IS NOT NULL AS approved, error, "
                    "withdrawal_reason FROM sources"
                )
            finally:
                await conn.close()
            return {
                r["title"]: (r["status"], r["approved"], r["error"], r["withdrawal_reason"])
                for r in rows
            }

        asyncio.run(arrange())
        migrate(db)
        assert asyncio.run(check()) == {
            "registered": ("proposed", False, None, None),
            "ingesting": ("failed", True, "ingestion did not finish (before Phase 1b)", None),
            "ingested": ("ingested", True, None, None),
            "withdrawn": ("withdrawn", True, None, "withdrawn before Phase 1b"),
        }
        migrate(db, "0012", down=True)
    finally:
        asyncio.run(_execute(admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def test_proposed_metadata_is_the_rows(
    env: tuple[Env, Ingest], admin_conn: asyncpg.Connection
) -> None:
    e, _ = env
    submission = await propose(
        e.factory,
        TAGS,
        load_path(PDF),
        SourceMetadata(**{**meta("sample-reports").__dict__, "downloadable": True}),
        content_root=e.content_root,
        proposer_id=None,
    )
    row = await source_row(admin_conn, submission.source_id)
    assert (row["status"], row["proposed_by"], row["downloadable"]) == ("proposed", None, True)
    [event] = await events(admin_conn, submission.source_id)
    assert (event["actor"], event["method"]) == (None, "cli")


def test_audit_allow_list_takes_roles_and_self_approval_as_scalars_only() -> None:
    from app.audit.writer import ForbiddenAuditField, _check

    _check({"roles": ["content_editor", "content_reviewer"], "self_approval": True})
    with pytest.raises(ForbiddenAuditField):
        _check({"roles": {"content_editor": True}})  # type: ignore[dict-item]
    with pytest.raises(ForbiddenAuditField):
        _check({"roles": ["x" * 200]})
    with pytest.raises(ForbiddenAuditField):
        _check({"review_note": "free text"})  # notes stay on the row, never in the audit
