"""P1a-04: workspaces, their packages, the conversation's fixed choice, prompt versions
and the operator's package builder. Against PostgreSQL as the application role."""

from __future__ import annotations

import ast
import inspect
import json
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat import package
from app.chat.context import select_context
from app.chat.package import provenance_by_document, workspace_package
from app.content.tags import TagConfig, load_tags
from app.core.config import Settings
from app.core.db import session_factory, tenant_session
from app.retrieval.types import RetrievedChunk
from app.tenancy import workspaces
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import DATASETS, World, chunks_for
from tests.conftest import CONSENT_VERSION
from tests.fakes import FakeRedis, FakeRetriever, delta, sse
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_api import Harness, api  # noqa: F401 - fixture
from tests.test_auth import auth  # noqa: F401 - fixture
from tests.test_operator import MODEL, Console, console, owner  # noqa: F401 - fixtures
from tests.test_orchestrator import orchestrator, run

pytestmark = pytest.mark.usefixtures("database")

APP_DIR = Path(__file__).resolve().parents[1] / "app"
WEB_DATASET = "ds-web-0001"


async def _sync_web_dataset(admin: asyncpg.Connection) -> None:
    await admin.execute(
        "INSERT INTO datasets (tag, ragflow_dataset_id) VALUES ('sample-web', $1) "
        "ON CONFLICT (tag) DO NOTHING",
        WEB_DATASET,
    )


async def _package(engine: AsyncEngine, workspace_id: uuid.UUID) -> package.Package:
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        return await workspace_package(session, workspace_id)


# --- dataset IDs come from the workspace row, never from the request ----------------------


@pytest.mark.parametrize("module", [package, workspaces])
def test_package_resolution_cannot_see_a_request(module: Any) -> None:
    """Nothing that resolves a workspace's datasets imports or accepts a request."""
    tree = ast.parse(inspect.getsource(module))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imported & {"fastapi", "starlette"}
    for name, function in inspect.getmembers(module, inspect.iscoroutinefunction):
        assert "request" not in inspect.signature(function).parameters, name


async def test_workspace_package_resolves_its_own_tags_only(
    engine: AsyncEngine, world: World
) -> None:
    reports_only = await world.new_workspace(["sample-reports"])
    resolved = await _package(engine, reports_only)
    assert resolved.tags == ("sample-reports",)
    assert resolved.dataset_ids == (DATASETS["sample-reports"],)


async def test_workspace_of_another_tenant_does_not_resolve(
    engine: AsyncEngine, world: World, admin_conn: asyncpg.Connection
) -> None:
    from tests.test_tenancy import make_tenant

    other = await make_tenant(admin_conn)
    await admin_conn.execute(
        "UPDATE workspaces SET tag_ids = ARRAY['sample-reports'] WHERE tenant_id = $1", other.id
    )
    foreign = await admin_conn.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", other.id)
    with pytest.raises(package.WorkspaceNotFound):
        await _package(engine, foreign)


async def test_conversation_body_cannot_carry_dataset_or_document_ids(api: Harness) -> None:  # noqa: F811
    for field in ("dataset_ids", "document_ids", "tag_ids"):
        response = await api.request("POST", "/conversations", json={field: ["ds-reports-0001"]})
        assert response.status_code == 422, field


async def test_retrieval_uses_the_conversations_workspace_datasets(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    analysis_only = await world.new_workspace(["sample-analysis"])
    conversation = await world.new_conversation(workspace_id=analysis_only)
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("Slowdown [1].")))
    await run(orchestrator(settings, engine, retriever, recorder), world, "Outlook?", conversation)
    assert [call["dataset_ids"] for call in retriever.calls] == [[DATASETS["sample-analysis"]]]


# --- shared tags and de-duplication (R15) -------------------------------------------------


async def test_shared_tag_overlaps_and_a_document_in_both_appears_once(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    await _sync_web_dataset(world.admin)
    first = await world.new_workspace(["sample-reports", "sample-analysis"])
    second = await world.new_workspace(["sample-reports", "sample-web"])
    a, b = await _package(engine, first), await _package(engine, second)
    assert set(a.dataset_ids) & set(b.dataset_ids) == {DATASETS["sample-reports"]}
    assert set(a.dataset_ids) ^ set(b.dataset_ids) == {DATASETS["sample-analysis"], WEB_DATASET}

    # One source ingested under two tags: two RAGFlow documents, different chunk IDs.
    doc_reports, doc_analysis = (f"doc-{uuid.uuid4().hex[:12]}" for _ in range(2))
    source = await world.admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, tags, status, approved_at, "
        "ragflow_document_ids) VALUES ('pdf', 'Shared Report', 'Synthetic Institute', "
        "'synthetic', ARRAY['sample-reports', 'sample-analysis'], 'ingested', now(), $1::jsonb) "
        "RETURNING id",
        json.dumps(
            {DATASETS["sample-reports"]: doc_reports, DATASETS["sample-analysis"]: doc_analysis}
        ),
    )
    text = "Shared synthetic storage reached 3 GW in 2025."
    chunks = [
        RetrievedChunk("chunk-r-1", doc_reports, DATASETS["sample-reports"], text, 0.7, 1),
        RetrievedChunk("chunk-a-9", doc_analysis, DATASETS["sample-analysis"], text, 0.6, 1),
    ]
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        provenance = await provenance_by_document(session, [doc_reports, doc_analysis])
    context = select_context(
        chunks, provenance, dataset_ids=a.dataset_ids, similarity_threshold=0.2, max_tokens=6000
    )
    assert [(c.chunk.chunk_id, c.provenance.source_id) for c in context] == [("chunk-r-1", source)]

    # And through the orchestrator: the model sees the passage once.
    conversation = await world.new_conversation(workspace_id=first)
    recorder = Recorder(sse(delta("Storage [1].")))
    await run(
        orchestrator(settings, engine, FakeRetriever(chunks), recorder),
        world,
        "Storage?",
        conversation,
    )
    prompt = json.loads(recorder.requests[0].content)["messages"][-1]["content"]
    assert prompt.count("<passage ") == 1


# --- starting a conversation: workspace, mode, model, reasoning ---------------------------


async def test_conversation_defaults_come_from_the_only_workspace(api: Harness) -> None:  # noqa: F811
    research = await api.world.admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1 AND slug = 'research'", INTERNAL_TENANT_ID
    )
    response = await api.request("POST", "/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["workspace_id"], body["mode"], body["model"], body["reasoning"]) == (
        str(research),
        "corpus_only",
        MODEL,
        False,
    )
    listed = (await api.request("GET", "/workspaces")).json()
    assert listed == [
        {
            "id": str(research),
            "slug": "research",
            "name": "Research",
            "default_mode": "corpus_only",
            "default_model": MODEL,
            "default_reasoning": False,
        }
    ]  # no tags, no dataset IDs


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"mode": "general_knowledge"}, "mode_not_enabled"),
        ({"model": "mistral-large-2512"}, "model_unavailable"),  # not in the catalogue
        ({"model": "openai/gpt-6.1-sol"}, "model_not_enabled"),
    ],
)
async def test_choice_outside_the_entitlements_is_refused(
    api: Harness,  # noqa: F811
    body: dict[str, Any],
    code: str,
) -> None:
    response = await api.request("POST", "/conversations", json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": code}


async def test_enabled_mode_and_reasoning_are_stored(api: Harness) -> None:  # noqa: F811
    await api.world.admin.execute(
        "UPDATE tenant_entitlements SET answer_modes = ARRAY['corpus_only', 'general_knowledge'], "
        "enabled_models = ARRAY[$2, 'qwen3.8-27b'] WHERE tenant_id = $1",
        INTERNAL_TENANT_ID,
        MODEL,
    )
    try:
        # Qwen: a model that may reason (DeepSeek offers off only).
        response = await api.request(
            "POST",
            "/conversations",
            json={"mode": "general_knowledge", "model": "qwen3.8-27b", "reasoning": True},
        )
    finally:
        await api.world.admin.execute(
            "UPDATE tenant_entitlements SET answer_modes = ARRAY['corpus_only'], "
            "enabled_models = ARRAY[$2] WHERE tenant_id = $1",
            INTERNAL_TENANT_ID,
            MODEL,
        )
    assert response.status_code == 201
    row = await api.world.admin.fetchrow(
        "SELECT mode, model, reasoning FROM conversations WHERE id = $1",
        uuid.UUID(response.json()["id"]),
    )
    assert dict(row) == {"mode": "general_knowledge", "model": "qwen3.8-27b", "reasoning": True}


async def test_two_workspaces_need_an_explicit_choice(api: Harness) -> None:  # noqa: F811
    second = await api.world.new_workspace(["sample-reports"])
    try:
        refused = await api.request("POST", "/conversations")
        assert refused.status_code == 422 and refused.json() == {"detail": "workspace_required"}
        chosen = await api.request("POST", "/conversations", json={"workspace_id": str(second)})
        assert chosen.status_code == 201 and chosen.json()["workspace_id"] == str(second)
        unknown = await api.request(
            "POST", "/conversations", json={"workspace_id": str(uuid.uuid4())}
        )
        assert unknown.status_code == 404
    finally:
        await api.world.drop_workspaces()


async def test_workspace_model_and_reasoning_cannot_change_after_creation(
    app_conn: asyncpg.Connection, world: World
) -> None:
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(INTERNAL_TENANT_ID))
    other = await world.new_workspace(["sample-web"])
    for column, value in (
        ("workspace_id", other),
        ("model", "qwen3.8-27b"),
        ("reasoning", True),
        ("mode", "general_knowledge"),
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            await app_conn.execute(
                f"UPDATE conversations SET {column} = $1 WHERE id = $2",
                value,
                world.conversation_id,
            )
    # The title and timestamps stay writable.
    await app_conn.execute(
        "UPDATE conversations SET title = 'renamed', updated_at = now() WHERE id = $1",
        world.conversation_id,
    )


# --- tenant isolation over the API ----------------------------------------------------------


async def test_tenant_b_user_cannot_read_tenant_a_workspaces(console: Console) -> None:  # noqa: F811
    a = await console.auth.tenant(role="tenant_admin")
    b = await console.auth.tenant(role="tenant_admin")
    a_workspace = await console.auth.admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1", a.id
    )
    b_browser = console.as_user(b.email, b.id)

    listed = (await b_browser.get("/api/v1/workspaces")).json()
    assert [w["id"] for w in listed] != [str(a_workspace)]
    assert str(a_workspace) not in json.dumps(listed)
    assert (await b_browser.get(f"/api/v1/workspaces/{a_workspace}/prompts")).status_code == 404
    saved = await b_browser.put(
        f"/api/v1/workspaces/{a_workspace}/prompt", json={"text": "Synthetic."}
    )
    assert saved.status_code == 404
    started = await b_browser.post("/api/v1/conversations", json={"workspace_id": str(a_workspace)})
    assert started.status_code == 404
    assert (
        await console.auth.admin.fetchval(
            "SELECT count(*) FROM workspace_prompts WHERE workspace_id = $1", a_workspace
        )
        == 0
    )


async def test_tenant_without_workspace_cannot_start_a_conversation(
    console: Console,  # noqa: F811
) -> None:
    t = await console.auth.tenant()
    await console.auth.admin.execute("DELETE FROM workspaces WHERE tenant_id = $1", t.id)
    response = await console.as_user(t.email, t.id).post("/api/v1/conversations")
    assert response.status_code == 422 and response.json() == {"detail": "no_workspace"}


# --- workspace prompts: versions, admins only -----------------------------------------------


async def test_admin_saves_prompt_versions_and_users_cannot(console: Console) -> None:  # noqa: F811
    admin = await console.auth.tenant(role="tenant_admin")
    workspace = await console.auth.admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1", admin.id
    )
    browser = console.as_user(admin.email, admin.id)
    first = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt", json={"text": "  Prefer recent sources.  "}
    )
    second = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt", json={"text": "Answer in British English."}
    )
    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["text"] == "Prefer recent sources."
    history = (await browser.get(f"/api/v1/workspaces/{workspace}/prompts")).json()
    assert [h["version"] for h in history] == [2, 1]
    assert await console.auth.audit("workspace.prompt_saved", admin.id) == [
        {"actor": admin.user_id, "workspace_id": str(workspace), "version": 1},
        {"actor": admin.user_id, "workspace_id": str(workspace), "version": 2},
    ]

    too_long = await browser.put(
        f"/api/v1/workspaces/{workspace}/prompt", json={"text": "x" * 2001}
    )
    assert too_long.status_code == 422

    user_id = await console.auth.admin.fetchval(
        "INSERT INTO users (tenant_id, email, display_name, role, consent_version, consented_at) "
        "VALUES ($1, $2, 'Synthetic Reader', 'user', $3, now()) RETURNING id",
        admin.id,
        f"reader-{uuid.uuid4().hex[:6]}@client.example",
        CONSENT_VERSION,
    )
    reader_email = await console.auth.admin.fetchval(
        "SELECT email FROM users WHERE id = $1", user_id
    )
    reader = console.as_user(reader_email, admin.id)
    assert (
        await reader.put(f"/api/v1/workspaces/{workspace}/prompt", json={"text": "x"})
    ).status_code == 403
    assert (await reader.get(f"/api/v1/workspaces/{workspace}/prompts")).status_code == 403


async def test_prompt_versions_are_append_only_for_the_app(
    app_conn: asyncpg.Connection, world: World
) -> None:
    research = await world.admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1 AND slug = 'research'", INTERNAL_TENANT_ID
    )
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(INTERNAL_TENANT_ID))
    prompt = await app_conn.fetchval(
        "INSERT INTO workspace_prompts (tenant_id, workspace_id, version, text, author_user_id) "
        "VALUES ($1, $2, 900, 'Synthetic.', $3) RETURNING id",
        INTERNAL_TENANT_ID,
        research,
        world.user_id,
    )
    try:
        for statement in (
            "UPDATE workspace_prompts SET text = 'changed' WHERE id = $1",
            "DELETE FROM workspace_prompts WHERE id = $1",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await app_conn.execute(statement, prompt)
        with pytest.raises(asyncpg.CheckViolationError, match="text_length"):
            await app_conn.execute(
                "INSERT INTO workspace_prompts (tenant_id, workspace_id, version, text, "
                "author_user_id) VALUES ($1, $2, 901, $3, $4)",
                INTERNAL_TENANT_ID,
                research,
                "x" * 2001,
                world.user_id,
            )
    finally:
        await world.admin.execute("DELETE FROM workspace_prompts WHERE id = $1", prompt)


# --- operator: the package builder ----------------------------------------------------------


async def test_operator_creates_workspaces_and_assigns_tags(
    console: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The repository's sample-* tags are the internal tenant's (Oct 22, 2026); here they
    # are shared, so the synthetic tenant may use them (ownership: test_operator_console).
    def shared_samples(config_dir: Path) -> dict[str, TagConfig]:
        tags = load_tags(config_dir)
        return {
            tag: cfg.model_copy(update={"tenant": None, "shared": True})
            if tag.startswith("sample-")
            else cfg
            for tag, cfg in tags.items()
        }

    monkeypatch.setattr("app.api.operator.load_tags", shared_samples)
    op = await console.operator()
    t = await console.auth.tenant()
    base = f"/api/v1/operator/tenants/{t.id}/workspaces"
    created = await op.post(
        base,
        json={
            "slug": "markets",
            "name": "Markets",
            "tag_ids": ["sample-reports", "sample-analysis"],
            "default_model": MODEL,
        },
    )
    assert created.status_code == 201, created.text
    workspace = created.json()
    assert workspace["tag_ids"] == ["sample-analysis", "sample-reports"]
    # A tag may repeat across a tenant's workspaces (a common corpus).
    common = await op.post(
        base,
        json={
            "slug": "policy",
            "name": "Policy",
            "tag_ids": ["sample-reports"],
            "default_model": MODEL,
        },
    )
    assert common.status_code == 201

    retagged = await op.put(f"{base}/{workspace['id']}/tags", json={"tag_ids": ["sample-web"]})
    assert retagged.status_code == 200 and retagged.json()["tag_ids"] == ["sample-web"]
    operator_id = str(await console.operator_id())
    (event,) = await console.events("operator.workspace_tags_changed", t.id)
    assert event["operator_id"] == operator_id and event["actor"] is None
    assert event["before"]["tag_ids"] == ["sample-analysis", "sample-reports"]
    assert event["after"]["tag_ids"] == ["sample-web"]
    assert len(await console.events("operator.workspace_created", t.id)) == 2
    assert [w["slug"] for w in (await op.get(base)).json()] == ["default", "markets", "policy"]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"tag_ids": ["not-a-tag"]}, 422, "unknown_tag"),
        ({"default_mode": "general_knowledge"}, 422, "mode_not_enabled"),
        ({"default_model": "qwen3.8-27b"}, 422, "model_not_enabled"),
        ({"slug": "default"}, 409, "slug_taken"),
    ],
)
async def test_operator_workspace_validation(
    console: Console,  # noqa: F811
    body: dict[str, Any],
    status: int,
    code: str,
) -> None:
    op = await console.operator()
    t = await console.auth.tenant()
    payload = {"slug": "markets", "name": "Markets", "tag_ids": [], "default_model": MODEL, **body}
    response = await op.post(f"/api/v1/operator/tenants/{t.id}/workspaces", json=payload)
    assert response.status_code == status and response.json() == {"detail": code}


async def test_tenant_admin_cannot_use_the_package_builder(console: Console) -> None:  # noqa: F811
    admin = await console.auth.tenant(role="tenant_admin")
    browser = console.as_user(admin.email, admin.id)
    base = f"/api/v1/operator/tenants/{admin.id}/workspaces"
    assert (await browser.get(base)).status_code == 403
    response = await browser.post(
        base, json={"slug": "mine", "name": "Mine", "tag_ids": [], "default_model": MODEL}
    )
    assert response.status_code == 403


async def test_operator_role_cannot_read_tenant_authored_prompts(
    admin_conn: asyncpg.Connection,
) -> None:
    privileges = await admin_conn.fetchval(
        "SELECT has_table_privilege('askspore_operator', 'workspace_prompts', 'SELECT')"
    )
    assert privileges is False
