"""P1b-10: the first-login consent gate.

No conversation, file or tenant admin route works before the user accepts the active
use and privacy notice; a new notice version re-prompts; acceptance is audited and in
the tenant admin's audit export; the operator and content consoles are not gated; a
version change queues one consent-notice email per user. Synthetic users only."""

from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.consent.notice import (
    PLACEHOLDER_MARKER,
    ConsentNoticeError,
    check_notice,
    load_notice,
)
from app.consent.notices import ConsentNoticeTick, queue_consent_notices
from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, load_settings
from app.core.db import session_factory
from tests.conftest import CONSENT_DEFAULTS_SQL, CONSENT_VERSION
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_config import ENV, SYNTHETIC_NOTICE, write_config
from tests.test_ingest import content_user
from tests.test_operator import OPERATOR_EMAIL, Console, console, owner  # noqa: F401
from tests.test_tenancy import Tenant, make_tenant
from tests.test_tenant_admin import add_user, as_user

REFUSED = (403, "consent_required")


async def unconsented(harness: Auth, role: str = "user") -> tuple[Tenant, httpx.AsyncClient]:
    """A tenant whose one user has never accepted a notice (their first sign-in)."""
    tenant = await make_tenant(harness.admin, role=role, consent_version=None)
    return tenant, as_user(harness, tenant.email, tenant.id)


async def arrange_conversation(admin: asyncpg.Connection, tenant: Tenant) -> tuple[str, str]:
    """A conversation with one assistant message, owned by ``tenant``'s user."""
    conversation = await admin.fetchval(
        "INSERT INTO conversations (tenant_id, user_id, workspace_id, mode, model, reasoning) "
        "VALUES ($1, $2, (SELECT id FROM workspaces WHERE tenant_id = $1 LIMIT 1), "
        "'corpus_only', 'deepseek-v4.1-flash', false) RETURNING id",
        tenant.id,
        tenant.user_id,
    )
    message = await admin.fetchval(
        "INSERT INTO messages (tenant_id, conversation_id, role, content) "
        "VALUES ($1, $2, 'assistant', 'Synthetic answer.') RETURNING id",
        tenant.id,
        conversation,
    )
    return str(conversation), str(message)


def result(response: httpx.Response) -> tuple[int, Any]:
    return response.status_code, response.json().get("detail")


def gated_requests(workspace: str, conversation: str, message: str) -> list[tuple[str, str, Any]]:
    source = str(uuid.uuid4())
    return [
        ("GET", "/api/v1/conversations", None),
        ("GET", f"/api/v1/conversations/{conversation}", None),
        ("POST", "/api/v1/conversations", {}),
        ("POST", f"/api/v1/conversations/{conversation}/messages", {"question": "Synthetic?"}),
        ("DELETE", f"/api/v1/conversations/{conversation}", None),
        ("POST", f"/api/v1/messages/{message}/feedback", {"rating": "up"}),
        ("GET", "/api/v1/workspaces", None),
        ("GET", "/api/v1/models", None),
        ("GET", f"/api/v1/sources/{source}", None),
        ("GET", f"/api/v1/workspaces/{workspace}/files", None),
        ("POST", f"/api/v1/workspaces/{workspace}/files/{source}/download", None),
        ("GET", "/api/v1/files/synthetic-token", None),
    ]


async def workspace_of(admin: asyncpg.Connection, tenant: Tenant) -> str:
    return str(await admin.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", tenant.id))


# --- the gate ---------------------------------------------------------------------------------


async def test_no_conversation_route_works_before_acceptance(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await unconsented(auth)
    conversation, message = await arrange_conversation(auth.admin, tenant)
    workspace = await workspace_of(auth.admin, tenant)
    for method, path, body in gated_requests(workspace, conversation, message):
        response = await browser.request(method, path, json=body)
        assert result(response) == REFUSED, (method, path)
    # Nothing was changed or recorded by the refused requests.
    assert (
        await auth.admin.fetchval(
            "SELECT count(*) FROM conversations WHERE tenant_id = $1", tenant.id
        )
        == 1
    )
    assert (
        await auth.admin.fetchval("SELECT count(*) FROM feedback WHERE tenant_id = $1", tenant.id)
        == 0
    )
    # Only the user's own details and the notice itself answer.
    me = await browser.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["consent_required"] is True
    notice = await browser.get("/api/v1/consent")
    assert notice.status_code == 200 and notice.json()["required"] is True
    assert (await browser.get("/api/v1/healthz")).status_code == 200


async def test_acceptance_opens_the_routes_and_is_audited(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await unconsented(auth)
    notice = (await browser.get("/api/v1/consent")).json()
    assert notice["version"] == CONSENT_VERSION
    assert notice["summary"] and notice["text"] and notice["title"]
    assert (notice["accepted_version"], notice["accepted_at"]) == (None, None)

    accepted = await browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["required"] is False
    assert accepted.json()["accepted_version"] == CONSENT_VERSION
    row = await auth.admin.fetchrow(
        "SELECT consent_version, consented_at FROM users WHERE id = $1", tenant.user_id
    )
    assert row["consent_version"] == CONSENT_VERSION and row["consented_at"] is not None
    assert await auth.audit("consent.accepted", tenant.id) == [
        {"actor": tenant.user_id, "version": CONSENT_VERSION}
    ]
    assert (await browser.get("/api/v1/conversations")).status_code == 200
    assert (await browser.get("/api/v1/me")).json()["consent_required"] is False

    again = await browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})
    assert again.status_code == 200
    assert len(await auth.audit("consent.accepted", tenant.id)) == 1  # recorded once


async def test_only_the_active_version_can_be_accepted(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await unconsented(auth)
    stale = await browser.post("/api/v1/consent", json={"version": "v999"})
    assert result(stale) == (409, "consent_version_stale")
    malformed = await browser.post("/api/v1/consent", json={"version": "latest"})
    assert malformed.status_code == 422
    extra = await browser.post(
        "/api/v1/consent", json={"version": CONSENT_VERSION, "user_id": str(uuid.uuid4())}
    )
    assert extra.status_code == 422  # nothing but the version is taken from the body
    assert await auth.audit("consent.accepted", tenant.id) == []


async def test_acceptance_is_the_callers_own(auth: Auth) -> None:  # noqa: F811
    """Accepting changes the signed-in user's row only, in their own tenant."""
    tenant, browser = await unconsented(auth)
    colleague = await add_user(auth.admin, tenant, consent_version=None)
    other, _ = await unconsented(auth)
    assert (await browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})).is_success
    for user_id in (colleague.user_id, other.user_id):
        assert (
            await auth.admin.fetchval("SELECT consent_version FROM users WHERE id = $1", user_id)
            is None
        )


def new_version_config(tmp_path: Path, version: str = "v2") -> Path:
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    (config / "consent" / f"{version}.md").write_text(SYNTHETIC_NOTICE, encoding="utf-8")
    return config


def activate(harness: Auth, config: Path, version: str) -> None:
    settings = harness.app.state.settings
    settings.config_dir = config
    settings.models = settings.models.model_copy(
        update={"consent": settings.models.consent.model_copy(update={"version": version})}
    )


async def test_a_new_notice_version_re_prompts(auth: Auth, tmp_path: Path) -> None:  # noqa: F811
    tenant = await make_tenant(auth.admin)  # accepted the current version
    browser = as_user(auth, tenant.email, tenant.id)
    assert (await browser.get("/api/v1/conversations")).status_code == 200

    activate(auth, new_version_config(tmp_path), "v2")
    assert result(await browser.get("/api/v1/conversations")) == REFUSED
    me = (await browser.get("/api/v1/me")).json()
    assert me["consent_required"] is True
    notice = (await browser.get("/api/v1/consent")).json()
    assert (notice["version"], notice["accepted_version"], notice["required"]) == (
        "v2",
        CONSENT_VERSION,
        True,
    )
    assert notice["summary"] == "Synthetic summary."
    old = await browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})
    assert result(old) == (409, "consent_version_stale")
    assert (await browser.post("/api/v1/consent", json={"version": "v2"})).is_success
    assert (await browser.get("/api/v1/conversations")).status_code == 200
    events = await auth.audit("consent.accepted", tenant.id)
    assert events == [{"actor": tenant.user_id, "version": "v2"}]


async def test_tenant_admin_pages_are_gated_like_users(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await unconsented(auth, role="tenant_admin")
    workspace = await workspace_of(auth.admin, tenant)
    for method, path, body in (
        ("GET", "/api/v1/admin/users", None),
        ("POST", "/api/v1/admin/users", {"email": "x@client.example", "display_name": "X"}),
        ("GET", "/api/v1/admin/settings", None),
        ("GET", "/api/v1/admin/audit-log", None),
        ("GET", f"/api/v1/workspaces/{workspace}/prompts", None),
        ("PUT", f"/api/v1/workspaces/{workspace}/prompt", {"text": "Synthetic."}),
    ):
        assert result(await browser.request(method, path, json=body)) == REFUSED, path
    assert (
        await auth.admin.fetchval("SELECT count(*) FROM users WHERE tenant_id = $1", tenant.id) == 1
    )  # the refused invite created nobody
    # A user who is not an admin still gets the role refusal first.
    member = await add_user(auth.admin, tenant, consent_version=None)
    plain = as_user(auth, member.email, tenant.id)
    assert result(await plain.get("/api/v1/admin/users")) == (403, "forbidden")


async def test_operator_and_content_consoles_are_not_gated(
    console: Console,  # noqa: F811
) -> None:
    """Internal tenant staff: the consoles are not conversation routes."""
    op = await console.operator()
    await content_user(console.auth.admin, "content_editor")
    admin = console.auth.admin
    await admin.execute(
        "UPDATE users SET consent_version = NULL, consented_at = NULL WHERE lower(email) = $1",
        OPERATOR_EMAIL,
    )
    try:
        assert (await op.get("/api/v1/operator/tenants")).status_code == 200
        assert (await op.get("/api/v1/content/me")).status_code == 200
        assert (await op.get("/api/v1/content/sources")).status_code == 200
        # The same person's conversations are gated like everyone's.
        assert result(await op.get("/api/v1/conversations")) == REFUSED
    finally:  # a seeded user, shared with later tests
        await admin.execute(
            f"UPDATE users SET {CONSENT_DEFAULTS_SQL} WHERE lower(email) = $1", OPERATOR_EMAIL
        )


async def test_the_refusal_log_line_carries_identifiers_only(
    auth: Auth,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    tenant, browser = await unconsented(auth)
    capsys.readouterr()
    question = "Synthetic question about offshore wind?"
    await browser.post("/api/v1/conversations/x/messages", json={"question": question})
    await browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})
    logged = capsys.readouterr().out + "\n".join(r.getMessage() for r in caplog.records)
    assert '"event":"consent.refused"' in logged and '"event":"consent.accepted"' in logged
    assert question not in logged and tenant.email not in logged
    assert load_notice(DEFAULT_CONFIG_DIR, CONSENT_VERSION).text[:40] not in logged


# --- the audit export -------------------------------------------------------------------------


def export_rows(response: httpx.Response) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.text)))


async def test_the_tenant_admin_audit_export_includes_acceptance_events(
    auth: Auth,  # noqa: F811
) -> None:
    tenant, browser = await unconsented(auth, role="tenant_admin")
    member = await add_user(auth.admin, tenant, consent_version=None)
    member_browser = as_user(auth, member.email, tenant.id)
    for b in (browser, member_browser):
        assert (await b.post("/api/v1/consent", json={"version": CONSENT_VERSION})).is_success
    # Another tenant's acceptance, and this tenant's query event, stay out.
    other, other_browser = await unconsented(auth)
    await other_browser.post("/api/v1/consent", json={"version": CONSENT_VERSION})
    await auth.admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event, metadata) "
        "VALUES ($1, $2, 'chat.query', '{\"outcome\": \"answered\"}')",
        tenant.id,
        member.user_id,
    )

    rows = export_rows(await browser.get("/api/v1/admin/audit-log"))
    accepted = [r for r in rows if r["event"] == "consent.accepted"]
    assert {r["actor_user_id"] for r in accepted} == {str(tenant.user_id), str(member.user_id)}
    assert all(json.loads(r["metadata"]) == {"version": CONSENT_VERSION} for r in accepted)
    assert "chat.query" not in {r["event"] for r in rows}
    assert str(other.user_id) not in json.dumps(rows)
    assert list(rows[0]) == ["created_at", "event", "actor_user_id", "metadata"]
    # The export is itself audited; a later one lists it.
    later = export_rows(await browser.get("/api/v1/admin/audit-log?since=2026-01-01"))
    assert "tenant_admin.audit_exported" in {r["event"] for r in later}
    plain = as_user(auth, member.email, tenant.id)
    assert result(await plain.get("/api/v1/admin/audit-log")) == (403, "forbidden")


# --- the consent-notice email -----------------------------------------------------------------


async def mail_jobs(admin: asyncpg.Connection, template: str) -> list[dict[str, Any]]:
    rows = await admin.fetch(
        "SELECT payload FROM jobs WHERE type = 'send_mail' AND payload->>'template' = $1",
        template,
    )
    return [json.loads(r["payload"]) for r in rows]


async def test_a_version_change_queues_one_notice_email_per_user(
    engine: AsyncEngine, admin_conn: asyncpg.Connection
) -> None:
    factory = session_factory(engine)
    tenant = await make_tenant(admin_conn)  # accepted v1
    second = await add_user(admin_conn, tenant)  # accepted v1
    never = await add_user(admin_conn, tenant, consent_version=None)  # sees the gate anyway
    invited = await add_user(admin_conn, tenant, status="invited")
    gone = await add_user(admin_conn, tenant, status="deactivated")
    other = await make_tenant(admin_conn)
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'send_mail'")

    await queue_consent_notices(factory, CONSENT_VERSION)  # no change for these users
    assert await mail_jobs(admin_conn, "consent_notice") == [] or all(
        j["tenant_id"] not in (str(tenant.id), str(other.id))
        for j in await mail_jobs(admin_conn, "consent_notice")
    )
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'send_mail'")
    queued = await queue_consent_notices(factory, "v2")
    jobs = await mail_jobs(admin_conn, "consent_notice")
    recipients = {(j["tenant_id"], j["user_id"]) for j in jobs}
    mine = {(str(tenant.id), str(u)) for u in (tenant.user_id, second.user_id)}
    assert mine <= recipients and (str(other.id), str(other.user_id)) in recipients
    for user in (never, invited, gone):
        assert all(j["user_id"] != str(user.user_id) for j in jobs)
    assert queued == len(jobs)
    assert all(set(j) == {"template", "tenant_id", "user_id"} for j in jobs)  # IDs only

    # Once per user per version, however often the tick runs; a later version mails again.
    assert await queue_consent_notices(factory, "v2") == 0
    await admin_conn.execute("UPDATE jobs SET status = 'succeeded' WHERE type = 'send_mail'")
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'send_mail'")
    await queue_consent_notices(factory, "v3")
    again = {(j["tenant_id"], j["user_id"]) for j in await mail_jobs(admin_conn, "consent_notice")}
    assert mine <= again
    # A user who accepts the new version is not mailed about it.
    await admin_conn.execute(
        "UPDATE users SET consent_version = 'v4', consented_at = now() WHERE id = $1",
        second.user_id,
    )
    await admin_conn.execute("UPDATE jobs SET status = 'succeeded' WHERE type = 'send_mail'")
    await queue_consent_notices(factory, "v4")
    latest = await admin_conn.fetch(
        "SELECT payload->>'user_id' AS user_id FROM jobs WHERE type = 'send_mail' "
        "AND status = 'queued'"
    )
    assert str(second.user_id) not in {r["user_id"] for r in latest}


async def test_the_tick_runs_at_most_once_an_interval(
    engine: AsyncEngine, admin_conn: asyncpg.Connection
) -> None:
    now = [0.0]
    tick = ConsentNoticeTick(session_factory(engine), "v2", interval=60, clock=lambda: now[0])
    await make_tenant(admin_conn)
    assert await tick() >= 1
    await make_tenant(admin_conn)
    now[0] = 30
    assert await tick() == 0  # too soon
    now[0] = 61
    assert await tick() >= 1


# --- the notice file and the schema -------------------------------------------------------


def test_the_repository_notice_is_the_owners_placeholder() -> None:
    """v1 quotes the privacy notice draft's title and invents no legal text."""
    notice = load_notice(DEFAULT_CONFIG_DIR, CONSENT_VERSION)
    draft_title = (
        (DEFAULT_CONFIG_DIR.parent / "design" / "compliance" / "privacy-notice.md")
        .read_text(encoding="utf-8")
        .splitlines()[0]
        .removeprefix("# ")
    )
    assert notice.title == draft_title
    assert notice.is_placeholder
    assert PLACEHOLDER_MARKER in notice.summary and PLACEHOLDER_MARKER in notice.text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "No title\n\n## Summary\n\nS\n\n## Full notice\n\nN\n",
        "# T\n\n## Full notice\n\nN\n",
        "# T\n\n## Summary\n\nS\n",
        "# T\n\n## Summary\n\n\n## Full notice\n\nN\n",
        "# T\n\n## Full notice\n\nN\n\n## Summary\n\nS\n",
    ],
)
def test_a_malformed_notice_refuses_startup(tmp_path: Path, text: str) -> None:
    config = write_config(tmp_path)
    (config / "consent" / "v1.md").write_text(text, encoding="utf-8")
    assert check_notice(config, "v1")
    with pytest.raises(ConsentNoticeError):
        load_notice(config, "v1")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config)
    assert any(p.startswith("consent.version") for p in excinfo.value.problems)


def test_a_missing_notice_version_refuses_startup(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    (config / "consent" / "v1.md").unlink()
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config)
    assert any(p.startswith("consent.version") for p in excinfo.value.problems)


async def test_the_schema_records_version_and_time_together(
    admin_conn: asyncpg.Connection,
) -> None:
    tenant = await make_tenant(admin_conn, consent_version=None)
    for sql in (
        "UPDATE users SET consent_version = 'v1' WHERE id = $1",
        "UPDATE users SET consented_at = now() WHERE id = $1",
        "UPDATE users SET consent_version = 'latest', consented_at = now() WHERE id = $1",
        "UPDATE users SET consent_notice_version = 'final' WHERE id = $1",
    ):
        with pytest.raises(asyncpg.CheckViolationError):
            await admin_conn.execute(sql, tenant.user_id)


async def test_the_application_role_updates_only_its_tenants_consent(
    app_conn: asyncpg.Connection, admin_conn: asyncpg.Connection
) -> None:
    mine = await make_tenant(admin_conn, consent_version=None)
    other = await make_tenant(admin_conn, consent_version=None)
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(mine.id))
    status = await app_conn.execute(
        f"UPDATE users SET {CONSENT_DEFAULTS_SQL} WHERE id = ANY($1::uuid[])",
        [mine.user_id, other.user_id],
    )
    assert status == "UPDATE 1"
    assert (
        await admin_conn.fetchval("SELECT consent_version FROM users WHERE id = $1", other.user_id)
        is None
    )
