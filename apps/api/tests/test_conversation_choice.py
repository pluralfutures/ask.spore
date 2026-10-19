"""Group B and C integration (findings C17): creating a conversation stores the model
and reasoning ``choose_for_new_conversation`` picks, defaults from the workspace, and
returns the spend-cap notice. Through the API, against PostgreSQL."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import World
from tests.test_api import Harness, api
from tests.test_model_catalogue import CLAUDE, DEEPSEEK, QWEN, internal_entitlement
from tests.test_spend_cap import ledger

__all__ = ["api", "internal_entitlement", "ledger"]  # fixtures

pytestmark = pytest.mark.usefixtures("database")


async def _workspace(world: World, model: str, reasoning: bool) -> uuid.UUID:
    workspace = await world.new_workspace(["sample-reports"])
    await world.admin.execute(
        "UPDATE workspaces SET default_model = $2, default_reasoning = $3 WHERE id = $1",
        workspace,
        model,
        reasoning,
    )
    return workspace


async def _create(api: Harness, **body: Any) -> dict[str, Any]:
    response = await api.request("POST", "/conversations", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    stored = await api.world.admin.fetchrow(
        "SELECT model, reasoning FROM conversations WHERE id = $1", uuid.UUID(created["id"])
    )
    assert stored is not None
    assert (stored["model"], stored["reasoning"]) == (created["model"], created["reasoning"])
    return created


async def test_workspace_defaults_are_stored(api: Harness, internal_entitlement: Any) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    workspace = await _workspace(api.world, QWEN, True)
    created = await _create(api, workspace_id=str(workspace))
    assert (created["model"], created["reasoning"], created["notice"]) == (QWEN, True, None)
    # The user's reasoning switch wins over the workspace default.
    created = await _create(api, workspace_id=str(workspace), reasoning=False)
    assert (created["model"], created["reasoning"]) == (QWEN, False)


async def test_unusable_workspace_default_gives_way_to_the_eu_fallback(
    api: Harness, internal_entitlement: Any
) -> None:
    # The workspace default is external, the tenant is not entitled to external models.
    await internal_entitlement([DEEPSEEK, CLAUDE])
    workspace = await _workspace(api.world, CLAUDE, True)
    created = await _create(api, workspace_id=str(workspace))
    assert (created["model"], created["reasoning"]) == (DEEPSEEK, False)


async def test_external_choice_without_entitlement_is_refused(
    api: Harness, internal_entitlement: Any
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE])
    before = await api.world.admin.fetchval(
        "SELECT count(*) FROM conversations WHERE user_id = $1", api.world.user_id
    )
    response = await api.request("POST", "/conversations", json={"model": CLAUDE})
    assert (response.status_code, response.json()) == (422, {"detail": "external_not_entitled"})
    after = await api.world.admin.fetchval(
        "SELECT count(*) FROM conversations WHERE user_id = $1", api.world.user_id
    )
    assert after == before


async def test_cap_reached_falls_back_to_the_workspace_default_with_a_notice(
    api: Harness, internal_entitlement: Any, ledger: Any
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN, CLAUDE], external=True, cap=100)
    await ledger(CLAUDE, "100")
    workspace = await _workspace(api.world, QWEN, False)
    started = datetime.now(UTC)
    created = await _create(api, workspace_id=str(workspace), model=CLAUDE, reasoning=True)
    assert (created["model"], created["reasoning"]) == (QWEN, True)
    assert created["notice"] == "external_spend_cap_reached"
    assert "Qwen" in created["notice_text"]
    audit = await api.world.admin.fetchval(
        "SELECT metadata FROM audit_events WHERE tenant_id = $1 AND event = 'model.fallback' "
        "AND created_at >= $2",
        INTERNAL_TENANT_ID,
        started,
    )
    assert json.loads(audit)["requested_model"] == CLAUDE


async def test_cap_reached_with_an_external_workspace_default_falls_back_to_eu(
    api: Harness, internal_entitlement: Any, ledger: Any
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await ledger(CLAUDE, "100")
    workspace = await _workspace(api.world, CLAUDE, False)
    created = await _create(api, workspace_id=str(workspace))
    assert (created["model"], created["notice"]) == (DEEPSEEK, "external_spend_cap_reached")


async def test_below_cap_external_choice_is_kept(
    api: Harness, internal_entitlement: Any, ledger: Any
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    created = await _create(api, model=CLAUDE)
    assert (created["model"], created["reasoning"], created["notice"]) == (CLAUDE, False, None)
