"""P1a-07: tenant-name flag on saved workspace prompts. A match writes an operator
notice and an audit row; the save succeeds and nothing reveals the match to the user."""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest

from app.tenancy.name_flags import match_kinds
from tests.test_auth import auth  # noqa: F401 - fixture
from tests.test_operator import Console, console, owner  # noqa: F401 - fixtures
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

NOTICE = "workspace_prompt.tenant_name_match"
TERMS = {
    "tenant_name": ["Acme Analytics"],
    "domain": ["acme-analytics.example"],
    "user_name": ["Jo Bloggs", "Al"],
    "user_email": ["jo.bloggs@acme-analytics.example"],
}


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("Write for ACME ANALYTICS readers.", ["tenant_name"]),
        ("Write for acme\n  analytics readers.", ["tenant_name"]),
        ("Link to acme-analytics.example where useful.", ["domain"]),
        ("Ask jo.bloggs@acme-analytics.example.", ["domain", "user_email"]),
        ("Jo Bloggs prefers tables.", ["user_name"]),
        ("Acme Analytics' Jo Bloggs prefers tables.", ["tenant_name", "user_name"]),
        # Whole words only, and very short names are ignored.
        ("Acme Analyticsville is fictional.", []),
        ("Sub-Acme Analytics2 is fictional.", []),
        ("Always cite all passages.", []),
        ("Prefer recent sources.", []),
    ],
)
def test_match_kinds(text: str, kinds: list[str]) -> None:
    assert match_kinds(text, TERMS) == kinds


def test_match_ignores_regex_syntax_in_names() -> None:
    assert match_kinds("Ask C++ Team (EU) first.", {"tenant_name": ["C++ Team (EU)"]}) == [
        "tenant_name"
    ]
    assert match_kinds("Ask anyone.", {"tenant_name": [".*"]}) == []


async def _admin_workspace(console: Console) -> tuple[Tenant, uuid.UUID, Any]:  # noqa: F811
    admin = await console.auth.tenant(role="tenant_admin")
    workspace = await console.auth.admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1", admin.id
    )
    return admin, workspace, console.as_user(admin.email, admin.id)


async def test_tenant_name_match_writes_notice_and_audit_and_reveals_nothing(
    console: Console,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, workspace, browser = await _admin_workspace(console)
    # make_tenant: display name "Synthetic Client", domain client.example.
    plain = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt", json={"text": "Prefer recent sources."}
    )
    named_text = "Write for the Synthetic Client board; contact " + admin.email
    named = await browser.put(f"/api/v1/workspaces/{workspace}/prompt", json={"text": named_text})

    # The save succeeds and the response is the same shape, with nothing about the match.
    assert plain.status_code == named.status_code == 200
    assert (
        set(plain.json())
        == set(named.json())
        == {
            "workspace_id",
            "version",
            "text",
            "created_at",
        }
    )
    assert named.json()["text"] == named_text
    for word in ("match", "flag", "notice", "tenant_name"):
        assert word not in named.text.lower()
    assert set(named.headers) == set(plain.headers)
    history = await browser.get(f"/api/v1/workspaces/{workspace}/prompts")
    assert "match" not in history.text.lower() and "notice" not in history.text.lower()

    notices = await console.auth.admin.fetch(
        "SELECT kind, metadata FROM operator_notices WHERE tenant_id = $1", admin.id
    )
    assert [(n["kind"], json.loads(n["metadata"])) for n in notices] == [
        (
            NOTICE,
            {
                "workspace_id": str(workspace),
                "version": 2,
                "match_kinds": ["tenant_name", "domain", "user_email"],
            },
        )
    ]
    assert await console.auth.audit("workspace.prompt_tenant_name_match", admin.id) == [
        {
            "actor": admin.user_id,
            "workspace_id": str(workspace),
            "version": 2,
            "match_kinds": ["tenant_name", "domain", "user_email"],
        }
    ]
    # Neither the notice, the audit row nor the logs hold the text that matched.
    stored = json.dumps([json.loads(n["metadata"]) for n in notices])
    out = capsys.readouterr().out
    for secret in ("Synthetic Client", admin.email, "client.example"):
        assert secret not in stored and secret not in out

    # The operator sees it in the console's notice list.
    op = await console.operator()
    listed = (await op.get("/api/v1/operator/notices")).json()
    assert any(n["kind"] == NOTICE and n["tenant_id"] == str(admin.id) for n in listed)


async def test_user_name_match_is_flagged(console: Console) -> None:  # noqa: F811
    admin, workspace, browser = await _admin_workspace(console)
    await console.auth.admin.execute(
        "INSERT INTO users (tenant_id, email, display_name) VALUES ($1, $2, 'Morwenna Trelawny')",
        admin.id,
        f"m-{uuid.uuid4().hex[:6]}@client.example",
    )
    response = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt",
        json={"text": "Morwenna   Trelawny reads these first."},
    )
    assert response.status_code == 200
    kinds = await console.auth.admin.fetchval(
        "SELECT metadata->'match_kinds' FROM operator_notices WHERE tenant_id = $1", admin.id
    )
    assert json.loads(kinds) == ["user_name"]


async def test_non_match_writes_nothing(console: Console) -> None:  # noqa: F811
    admin, workspace, browser = await _admin_workspace(console)
    for text in ("Prefer recent sources.", "", "Client examples are welcome."):
        response = await browser.put(f"/api/v1/workspaces/{workspace}/prompt", json={"text": text})
        assert response.status_code == 200
    assert (
        await console.auth.admin.fetchval(
            "SELECT count(*) FROM operator_notices WHERE tenant_id = $1", admin.id
        )
        == 0
    )
    assert await console.auth.audit("workspace.prompt_tenant_name_match", admin.id) == []


async def test_other_tenants_names_are_not_matched(console: Console) -> None:  # noqa: F811
    """Matching runs under the saving tenant's RLS scope: only its own names count."""
    other = await console.auth.tenant()
    await console.auth.admin.execute(
        "UPDATE tenants SET display_name = 'Zephyrine Holdings' WHERE id = $1", other.id
    )
    admin, workspace, browser = await _admin_workspace(console)
    response = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt", json={"text": "Compare with Zephyrine Holdings."}
    )
    assert response.status_code == 200
    assert (
        await console.auth.admin.fetchval(
            "SELECT count(*) FROM operator_notices WHERE tenant_id = ANY($1::uuid[])",
            [admin.id, other.id],
        )
        == 0
    )


async def test_app_role_may_add_notices_for_its_tenant_only_and_read_none(
    app_conn: asyncpg.Connection, admin_conn: asyncpg.Connection
) -> None:
    from tests.test_tenancy import make_tenant

    mine, theirs = await make_tenant(admin_conn), await make_tenant(admin_conn)
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(mine.id))
    await app_conn.execute(
        "INSERT INTO operator_notices (tenant_id, kind) VALUES ($1, 'test.notice')", mine.id
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await app_conn.execute(
            "INSERT INTO operator_notices (tenant_id, kind) VALUES ($1, 'test.notice')", theirs.id
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.fetchval("SELECT count(*) FROM operator_notices")
