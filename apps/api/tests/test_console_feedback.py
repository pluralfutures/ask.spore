"""P1c-08: the operator console and the chat app link to each other for operators only,
and a terminated tenant is listed as such with its purge date and certificate number."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.termination import terminate_tenant
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_operator import (  # noqa: F401 - fixtures
    OPERATOR_EMAIL,
    Console,
    console,
    create,
    owner,
)
from tests.test_tenant_admin import as_user

pytestmark = pytest.mark.usefixtures("database")


async def no_cache(_: uuid.UUID) -> int:
    return 0


async def test_me_says_operator_only_for_an_operator(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    assert (await op.get("/api/v1/me")).json()["operator"] is True

    # An internal user who is not an operator, and any client tenant's admin: no link.
    analyst = as_user(console.auth, "analyst@example.org", INTERNAL_TENANT_ID)
    assert (await analyst.get("/api/v1/me")).json()["operator"] is False
    client = await console.auth.tenant(role="tenant_admin")
    admin = as_user(console.auth, client.email, client.id)
    assert (await admin.get("/api/v1/me")).json()["operator"] is False
    # And the flag opens nothing by itself: the console still refuses them.
    assert (await admin.get("/api/v1/operator/tenants")).status_code == 403


async def test_a_terminated_tenant_is_listed_with_its_certificate(
    console: Console,  # noqa: F811
    owner: Any,  # noqa: F811
    tmp_path: Path,
) -> None:
    op = await console.operator()
    gone, kept = await create(op), await create(op)
    purge = await terminate_tenant(
        owner, slug=gone["slug"], confirm=gone["slug"], content_root=tmp_path, clear_cache=no_cache
    )

    response = await op.get("/api/v1/operator/terminated-tenants")

    assert response.status_code == 200, response.text
    listed = {t["id"]: t for t in response.json()}
    assert kept["id"] not in listed and str(INTERNAL_TENANT_ID) not in listed
    entry = listed[gone["id"]]
    assert entry["slug"] == gone["slug"]
    assert entry["status"] == "suspended"
    assert entry["certificate"] == purge.certificate_number
    assert entry["purged_at"] is not None
    # The active list still holds the others and not the purged one (Phase 1b F5).
    active = {t["id"] for t in (await op.get("/api/v1/operator/tenants")).json()}
    assert kept["id"] in active and gone["id"] not in active
    # An active tenant that merely lacks its login policy row is not "terminated".
    await console.auth.admin.execute(
        "DELETE FROM tenant_login_policy WHERE tenant_id = $1", uuid.UUID(kept["id"])
    )
    listed_again = {t["id"] for t in (await op.get("/api/v1/operator/terminated-tenants")).json()}
    assert kept["id"] not in listed_again and gone["id"] in listed_again


async def test_only_operators_see_terminated_tenants(auth: Auth) -> None:  # noqa: F811
    client = await auth.tenant(role="tenant_admin")
    admin = as_user(auth, client.email, client.id)
    assert (await admin.get("/api/v1/operator/terminated-tenants")).status_code == 403
    internal = as_user(auth, OPERATOR_EMAIL, INTERNAL_TENANT_ID)  # not granted here
    assert (await internal.get("/api/v1/operator/terminated-tenants")).status_code == 403
