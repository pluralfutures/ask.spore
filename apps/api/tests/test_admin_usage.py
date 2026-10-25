"""P2A-05: the tenant admin's usage section. Over HTTP in OIDC mode, against PostgreSQL
as the application role (RLS scopes every row).

Negative cases first: a tenant with no events gets zero rows, and two seeded tenants each
see their own counts only. The response schema's body-free check is in
``test_logging_policy`` beside the log-field check."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.usage.ledger import month_of
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_tenancy import Tenant
from tests.test_tenant_admin import add_user, admin_of, as_user

pytestmark = pytest.mark.usefixtures("database")

EXTERNAL = "openai/gpt-6.1-sol"


async def source(admin: asyncpg.Connection, title: str, publisher: str) -> uuid.UUID:
    source_id: uuid.UUID = await admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, tags) "
        "VALUES ('pdf', $1, $2, 'synthetic', ARRAY['sample-reports']) RETURNING id",
        title,
        publisher,
    )
    return source_id


async def query_event(
    admin: asyncpg.Connection,
    tenant: Tenant,
    user_id: uuid.UUID,
    *,
    mode: str = "corpus_only",
    cited: list[uuid.UUID] | None = None,
    days_ago: int = 0,
) -> None:
    metadata: dict[str, Any] = {
        "conversation_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "mode": mode,
        "outcome": "answered",
        "cited_source_ids": [str(s) for s in cited or []],
    }
    await admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event, metadata, created_at) "
        "VALUES ($1, $2, 'chat.query', $3::jsonb, $4)",
        tenant.id,
        user_id,
        json.dumps(metadata),
        datetime.now(UTC) - timedelta(days=days_ago),
    )


async def test_a_tenant_with_no_events_gets_zero_rows(auth: Auth) -> None:  # noqa: F811
    # Another tenant's activity must not leak into the empty one.
    busy = await auth.tenant()
    await query_event(auth.admin, busy, busy.user_id)
    _, browser = await admin_of(auth)
    response = await browser.get("/api/v1/admin/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["questions"] == [] and body["active_users"] == [] and body["top_sources"] == []
    assert body["costs"] is None and body["cost_month"] is None


async def test_each_tenant_sees_its_own_counts_only(auth: Auth) -> None:  # noqa: F811
    a, a_browser = await admin_of(auth)
    b, b_browser = await admin_of(auth)
    member = await add_user(auth.admin, a)
    report = await source(auth.admin, "Synthetic Wind Report", "Synthetic Institute")
    brief = await source(auth.admin, "Synthetic Grid Brief", "Synthetic Agency")
    other = await source(auth.admin, "Synthetic Other Paper", "Elsewhere")
    await query_event(auth.admin, a, a.user_id, cited=[report, brief])
    await query_event(auth.admin, a, member.user_id, cited=[report])
    await query_event(auth.admin, a, member.user_id, mode="general_knowledge")
    await query_event(auth.admin, a, member.user_id, days_ago=1, cited=[report])
    await query_event(auth.admin, a, member.user_id, days_ago=40, cited=[brief])  # outside
    for _ in range(3):
        await query_event(auth.admin, b, b.user_id, cited=[other])
    # Other events are not questions.
    await auth.admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event, metadata) "
        "VALUES ($1, $2, 'chat.feedback', '{\"rating\": \"up\"}')",
        a.id,
        a.user_id,
    )

    body = (await a_browser.get("/api/v1/admin/usage")).json()
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    assert body["until"] == today.isoformat()
    assert body["since"] == (today - timedelta(days=29)).isoformat()
    assert body["questions"] == [
        {"day": yesterday.isoformat(), "mode": "corpus_only", "questions": 1},
        {"day": today.isoformat(), "mode": "corpus_only", "questions": 2},
        {"day": today.isoformat(), "mode": "general_knowledge", "questions": 1},
    ]
    assert body["active_users"] == [
        {"day": yesterday.isoformat(), "users": 1},
        {"day": today.isoformat(), "users": 2},
    ]
    assert body["top_sources"] == [
        {"title": "Synthetic Wind Report", "publisher": "Synthetic Institute", "answers": 3},
        {"title": "Synthetic Grid Brief", "publisher": "Synthetic Agency", "answers": 1},
    ]
    raw = json.dumps(body)
    for leak in (str(member.user_id), str(a.user_id), str(b.user_id), "Elsewhere", member.email):
        assert leak not in raw
    assert "conversation_id" not in raw and "message_id" not in raw

    other_body = (await b_browser.get("/api/v1/admin/usage")).json()
    assert other_body["questions"] == [
        {"day": today.isoformat(), "mode": "corpus_only", "questions": 3}
    ]
    assert other_body["top_sources"] == [
        {"title": "Synthetic Other Paper", "publisher": "Elsewhere", "answers": 3}
    ]


async def test_costs_only_with_the_external_entitlement(auth: Auth) -> None:  # noqa: F811
    a, a_browser = await admin_of(auth)
    b, b_browser = await admin_of(auth)
    for tenant in (a, b):
        await auth.admin.execute(
            "INSERT INTO usage_ledger (tenant_id, month, model, tokens_in, tokens_out, "
            "cost_cents) VALUES ($1, $2, $3, 100, 50, 12.5)",
            tenant.id,
            month_of(),
            EXTERNAL,
        )
    await auth.admin.execute(
        "UPDATE tenant_entitlements SET external_models_enabled = true, "
        "external_acceptance_reference = 'DPA-synthetic', external_acceptance_date = now(), "
        "external_spend_cap_cents = 1000 WHERE tenant_id = $1",
        a.id,
    )
    body = (await a_browser.get("/api/v1/admin/usage")).json()
    assert body["cost_month"] == month_of().strftime("%Y-%m")
    assert [
        (c["model"], c["external"], c["tokens_in"], c["cost_cents"]) for c in body["costs"]
    ] == [(EXTERNAL, True, 100, "12.500000")]
    assert (await b_browser.get("/api/v1/admin/usage")).json()["costs"] is None


async def test_usage_is_for_tenant_admins_only(auth: Auth) -> None:  # noqa: F811
    tenant, _ = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    plain = as_user(auth, member.email, tenant.id)
    response = await plain.get("/api/v1/admin/usage")
    assert response.status_code == 403
