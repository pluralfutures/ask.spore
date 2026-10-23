"""P1b-12: the operator console, one tenant per page. The entitlement save names the
page's tenant (Phase 1a findings F2), tag pickers offer a tenant's own and shared tags
only, spend and token usage come from the ledger, and no route returns query text.
Over HTTP in OIDC mode, against PostgreSQL."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from app.usage.ledger import month_of
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_operator import (  # noqa: F401 - fixtures
    MODEL,
    Console,
    console,
    create,
    entitlements,
    owner,
)

pytestmark = pytest.mark.usefixtures("database")

CLAUDE = "anthropic/claude-opus-5.5"
MONTH = month_of()
LAST_MONTH = (MONTH - timedelta(days=1)).replace(day=1)
QUERY_TEXT = "Synthetic question qzv7731 about walnut pricing in Lisbon?"
ANSWER_TEXT = "Synthetic answer qzv7731 citing [1]."


async def tenant_with_slug(console: Console, op: httpx.AsyncClient, slug: str) -> str:  # noqa: F811
    existing = await console.auth.admin.fetchval("SELECT id FROM tenants WHERE slug = $1", slug)
    if existing is not None:
        return str(existing)
    return str((await create(op, slug=slug))["id"])


async def add_ledger(
    console: Console,  # noqa: F811
    tenant_id: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cents: str,
    month: Any = MONTH,
) -> None:
    await console.auth.admin.execute(
        "INSERT INTO usage_ledger (tenant_id, month, model, tokens_in, tokens_out, cost_cents) "
        "VALUES ($1, $2, $3, $4, $5, $6::numeric)",
        uuid.UUID(tenant_id),
        month,
        model,
        tokens_in,
        tokens_out,
        cents,
    )


# --- one tenant per page: the save names its page's tenant (F2) ----------------------------


async def test_an_entitlement_save_carries_its_pages_tenant(console: Console) -> None:  # noqa: F811
    """Phase 1a F2: cc's entitlements were saved on the internal tenant's panel. A save
    whose page tenant is not the path's tenant changes nothing on either."""
    op = await console.operator()
    page_tenant = (await create(op))["id"]
    other = (await create(op))["id"]
    before = await console.auth.admin.fetch(
        "SELECT tenant_id, answer_modes FROM tenant_entitlements WHERE tenant_id = ANY($1)",
        [uuid.UUID(page_tenant), uuid.UUID(other)],
    )
    body = entitlements(page_tenant, answer_modes=["general_knowledge", "corpus_only"])
    mixed = await op.put(f"/api/v1/operator/tenants/{other}/entitlements", json=body)
    assert (mixed.status_code, mixed.json()["detail"]) == (409, "tenant_mismatch")
    after = await console.auth.admin.fetch(
        "SELECT tenant_id, answer_modes FROM tenant_entitlements WHERE tenant_id = ANY($1)",
        [uuid.UUID(page_tenant), uuid.UUID(other)],
    )
    assert sorted(map(tuple, after)) == sorted(map(tuple, before))
    for tenant in (page_tenant, other):
        assert await console.events("operator.entitlements_changed", uuid.UUID(tenant)) == []

    # Without the page's tenant the save is refused outright, not defaulted.
    no_tenant = {k: v for k, v in body.items() if k != "tenant_id"}
    assert (
        await op.put(f"/api/v1/operator/tenants/{other}/entitlements", json=no_tenant)
    ).status_code == 422

    saved = await op.put(f"/api/v1/operator/tenants/{page_tenant}/entitlements", json=body)
    assert saved.status_code == 200
    (event,) = await console.events("operator.entitlements_changed", uuid.UUID(page_tenant))
    assert event["after"]["answer_modes"] == ["corpus_only", "general_knowledge"]
    assert await console.events("operator.entitlements_changed", uuid.UUID(other)) == []


async def test_one_tenant_and_its_users(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    email = f"admin-{uuid.uuid4().hex[:6]}@client.example"
    invited = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins", json={"email": email, "display_name": "A"}
    )
    assert invited.status_code == 201
    page = await op.get(f"/api/v1/operator/tenants/{tenant_id}")
    assert (page.status_code, page.json()["id"], page.json()["admins"]) == (200, tenant_id, 1)
    users = (await op.get(f"/api/v1/operator/tenants/{tenant_id}/users")).json()
    assert [(u["email"], u["role"], u["status"]) for u in users] == [
        (email, "tenant_admin", "invited")
    ]
    internal = (await op.get(f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/users")).json()
    assert email not in {u["email"] for u in internal}
    missing = uuid.uuid4()
    for path in ("", "/users", "/spend", "/tags"):
        assert (await op.get(f"/api/v1/operator/tenants/{missing}{path}")).status_code == 404


# --- tag pickers: the tenant's own tags and shared ones ----------------------------------


async def test_tag_picker_offers_the_tenants_own_and_shared_tags(console: Console) -> None:  # noqa: F811
    # The repository's tags all name a tenant (the sample-* tags are the internal
    # tenant's, owner decision of Oct 22, 2026); shared tags are covered in test_tags.
    op = await console.operator()
    cc = await tenant_with_slug(console, op, "cc")
    internal = await tenant_with_slug(console, op, "internal")
    other = (await create(op))["id"]

    async def offered(tenant: str) -> dict[str, bool]:
        response = await op.get(f"/api/v1/operator/tenants/{tenant}/tags")
        return {t["tag"]: t["shared"] for t in response.json()}

    assert await offered(other) == {}  # no other tenant's tags
    assert await offered(cc) == {
        "cc-shared": False,
        "cc-team1-healthcare-gpo": False,
        "cc-team2-college-universities": False,
        "cc-team3-commercial-restaurants": False,
    }
    assert await offered(internal) == {
        "sample-analysis": False,
        "sample-reports": False,
        "sample-web": False,
    }

    # The API refuses another tenant's tag, whatever the page offered.
    for tag in ("cc-shared", "sample-reports"):
        created = await op.post(
            f"/api/v1/operator/tenants/{other}/workspaces",
            json={
                "slug": "main",
                "name": "Main",
                "tag_ids": [tag],
                "default_mode": "corpus_only",
                "default_model": MODEL,
                "default_reasoning": False,
            },
        )
        assert (created.status_code, created.json()["detail"]) == (422, "tag_not_for_tenant")
    created = await op.post(
        f"/api/v1/operator/tenants/{cc}/workspaces",
        json={
            "slug": "drill",
            "name": "Drill",
            "tag_ids": ["cc-shared"],
            "default_mode": "corpus_only",
            "default_model": MODEL,
            "default_reasoning": False,
        },
    )
    assert created.status_code == 201
    workspace = created.json()["id"]
    path = f"/api/v1/operator/tenants/{cc}/workspaces/{workspace}/tags"
    refused = await op.put(path, json={"tag_ids": ["sample-web"]})
    assert (refused.status_code, refused.json()["detail"]) == (422, "tag_not_for_tenant")
    assert (await op.put(path, json={"tag_ids": ["cc-team1-healthcare-gpo"]})).status_code == 200


# --- spend and token usage from the ledger -----------------------------------------------


async def test_spend_matches_the_ledger(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    await op.put(
        f"/api/v1/operator/tenants/{tenant_id}/entitlements",
        json=entitlements(
            tenant_id,
            enabled_models=[MODEL, CLAUDE],
            external_models_enabled=True,
            external_spend_cap_cents=3000,
            external_acceptance={"reference": "DPA-SYN-002", "accepted_on": "2026-10-01"},
        ),
    )
    await add_ledger(console, tenant_id, MODEL, 120_000, 8_000, "8.640000")
    await add_ledger(console, tenant_id, CLAUDE, 50_000, 4_000, "2547.000000")
    await add_ledger(console, tenant_id, CLAUDE, 9_000_000, 9_000, "9999.000000", LAST_MONTH)
    await console.auth.admin.execute(
        "INSERT INTO spend_notices (tenant_id, month, threshold) VALUES ($1, $2, 80)",
        uuid.UUID(tenant_id),
        MONTH,
    )

    spend = (await op.get(f"/api/v1/operator/tenants/{tenant_id}/spend")).json()
    ledger = await console.auth.admin.fetch(
        "SELECT model, tokens_in, tokens_out, cost_cents FROM usage_ledger "
        "WHERE tenant_id = $1 AND month = $2 ORDER BY model",
        uuid.UUID(tenant_id),
        MONTH,
    )
    assert [
        (m["model"], m["tokens_in"], m["tokens_out"], Decimal(m["cost_cents"]))
        for m in spend["models"]
    ] == [tuple(r.values()) for r in ledger]
    assert {m["model"]: m["external"] for m in spend["models"]} == {CLAUDE: True, MODEL: False}
    assert spend["month"] == MONTH.strftime("%Y-%m")
    assert Decimal(spend["external_spent_cents"]) == Decimal("2547")  # Claude, this month only
    assert spend["external_spend_cap_cents"] == 3000
    eighty, hundred = spend["thresholds"]
    assert (eighty["percent"], Decimal(eighty["cents"]), eighty["reached"]) == (80, 2400, True)
    assert eighty["notified_at"] is not None
    assert (hundred["percent"], Decimal(hundred["cents"]), hundred["reached"]) == (100, 3000, False)
    assert hundred["notified_at"] is None


async def test_spend_without_a_cap_shows_no_thresholds(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    spend = (await op.get(f"/api/v1/operator/tenants/{tenant_id}/spend")).json()
    assert (spend["models"], spend["thresholds"], spend["external_spend_cap_cents"]) == (
        [],
        [],
        None,
    )
    assert Decimal(spend["external_spent_cents"]) == 0


async def test_aggregates_total_across_tenants_and_name_none(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    before = (await op.get("/api/v1/operator/aggregates")).json()
    a, b = (await create(op))["id"], (await create(op))["id"]
    await add_ledger(console, a, MODEL, 1000, 100, "0.780000")
    await add_ledger(console, b, MODEL, 2000, 200, "1.560000")
    await add_ledger(console, b, CLAUDE, 3000, 300, "1.782000")
    await add_ledger(console, a, CLAUDE, 1, 1, "500", LAST_MONTH)
    response = await op.get("/api/v1/operator/aggregates")
    after = response.json()

    def by_model(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {m["model"]: m for m in body["models"]}

    old, new = by_model(before), by_model(after)
    zero = {"tokens_in": 0, "tokens_out": 0, "cost_cents": "0", "tenants": 0}
    for model, tokens_in, cents, tenants in ((MODEL, 3000, "2.34", 2), (CLAUDE, 3000, "1.782", 1)):
        was = old.get(model, zero)
        assert new[model]["tokens_in"] - was["tokens_in"] == tokens_in
        assert Decimal(new[model]["cost_cents"]) - Decimal(was["cost_cents"]) == Decimal(cents)
        assert new[model]["tenants"] - was["tenants"] == tenants
    assert new[CLAUDE]["provider"] == "openrouter" and new[CLAUDE]["external"] is True
    providers = {p["provider"]: p for p in after["providers"]}
    assert Decimal(providers["openrouter"]["cost_cents"]) == sum(
        Decimal(m["cost_cents"]) for m in after["models"] if m["provider"] == "openrouter"
    )
    assert after["tenants_with_usage"] - before["tenants_with_usage"] == 2
    for tenant in (a, b):  # cross-tenant totals name no tenant
        assert tenant not in response.text


# --- no per-tenant query text in any response --------------------------------------------


async def test_no_console_route_returns_query_or_answer_text(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant_id = await tenant_with_slug(console, op, "cc")
    admin = console.auth.admin
    user_id = await admin.fetchval(
        "INSERT INTO users (tenant_id, email, display_name) VALUES ($1, $2, 'Synthetic User') "
        "RETURNING id",
        uuid.UUID(tenant_id),
        f"u-{uuid.uuid4().hex[:6]}@client.example",
    )
    workspace = await admin.fetchval(
        "INSERT INTO workspaces (tenant_id, slug, name, tag_ids, default_mode, default_model) "
        "VALUES ($1, $2, 'Synthetic', '{}', 'corpus_only', $3) RETURNING id",
        uuid.UUID(tenant_id),
        f"w-{uuid.uuid4().hex[:6]}",
        MODEL,
    )
    conversation = await admin.fetchval(
        "INSERT INTO conversations (tenant_id, user_id, workspace_id, mode, model, reasoning, "
        "title) VALUES ($1, $2, $3, 'corpus_only', $4, false, $5) RETURNING id",
        uuid.UUID(tenant_id),
        user_id,
        workspace,
        MODEL,
        QUERY_TEXT[:40],
    )
    for role, content in (("user", QUERY_TEXT), ("assistant", ANSWER_TEXT)):
        await admin.execute(
            "INSERT INTO messages (tenant_id, conversation_id, role, content) "
            "VALUES ($1, $2, $3, $4)",
            uuid.UUID(tenant_id),
            conversation,
            role,
            content,
        )
    await add_ledger(console, tenant_id, MODEL, 900, 40, "0.612000")

    paths = [
        "/api/v1/operator/me",
        "/api/v1/operator/options",
        "/api/v1/operator/tenants",
        "/api/v1/operator/notices",
        "/api/v1/operator/sources",
        "/api/v1/operator/aggregates",
        *(
            f"/api/v1/operator/tenants/{tenant_id}{suffix}"
            for suffix in ("", "/tags", "/users", "/spend", "/workspaces", "/login-policy")
        ),
    ]
    for path in paths:
        response = await op.get(path)
        assert response.status_code == 200, path
        for text in ("qzv7731", "walnut", "Lisbon", "Synthetic answer"):
            assert text not in response.text, (path, text)
    assert json.loads((await op.get(f"/api/v1/operator/tenants/{tenant_id}/spend")).text)["models"]
