"""P1a-09: model catalogue, split allow-list and the model entitlement check.

The negative cases prove the controls: startup refuses an unlisted or wrongly listed
host; a disabled model and an external model without the entitlement both fail closed
before any outbound call (mocked transports record nothing).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import ErrorEvent, Orchestrator
from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, Settings, load_settings
from app.core.db import session_factory
from app.llm import catalogue
from app.llm.catalogue import ModelChoice, cost_cents, entry
from app.main import create_app
from app.tenancy.entitlements import (
    ModelEntitlement,
    ModelRefused,
    check_choice,
    eu_fallback_choice,
    usable_models,
)
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, router
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_api import Harness, api
from tests.test_config import ENV, SCALEWAY_TOML, problems_for, write_config

__all__ = ["api"]  # fixture reused from the API tests

CLAUDE = "anthropic/claude-opus-5.5"
GPT = "openai/gpt-6.1-sol"
DEEPSEEK = "deepseek-v4.1-flash"
QWEN = "qwen3.8-27b"

OPENROUTER_TOML = (
    SCALEWAY_TOML.replace(
        'eu_hosts = ["api.mistral.ai", "api.scaleway.ai", "ragflow"]',
        'eu_hosts = ["api.mistral.ai", "api.scaleway.ai", "ragflow"]\n'
        'external_hosts = ["eu.openrouter.ai"]',
    )
    + """
[openrouter]
base_url = "https://eu.openrouter.ai/api/v1"
models = ["anthropic/claude-opus-5.5"]
timeout_seconds = 30

[[catalogue]]
id = "anthropic/claude-opus-5.5"
provider = "openrouter"
display_name = "Claude Opus 5.5"
reasoning = "effort"
price_in_cents_per_mtok = 500
price_out_cents_per_mtok = 2500
external = true
"""
)


# --- configuration ------------------------------------------------------------------------


def test_repository_catalogue() -> None:
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    models = settings.models
    assert [(e.id, e.provider, e.external) for e in models.catalogue] == [
        (DEEPSEEK, "scaleway", False),
        (QWEN, "scaleway", False),
        (GPT, "openrouter", True),
        (CLAUDE, "openrouter", True),
    ]
    assert models.scaleway is not None and QWEN in models.scaleway.models
    assert models.openrouter is not None and set(models.openrouter.models) == {GPT, CLAUDE}
    # OpenRouter's EU endpoint only (owner decision Oct 19, 2026, findings C25).
    assert models.allow_list.external_hosts == ("eu.openrouter.ai",)
    assert "eu.openrouter.ai" not in models.allow_list.eu_hosts
    assert models.openrouter.base_url == "https://eu.openrouter.ai/api/v1"
    # Every price is still a placeholder until the owner replaces it (findings C27).
    assert all(e.price_placeholder for e in models.catalogue)
    # The OpenRouter key is optional: without it, external models are refused.
    assert settings.secrets.openrouter_api_key is None


def test_startup_rejects_openrouters_global_host(tmp_path: Path) -> None:
    # Only the EU endpoint is allow-listed; the global API host is refused at startup.
    text = (DEFAULT_CONFIG_DIR / "models.toml").read_text()
    for host in ("api.openrouter.ai", "openrouter.ai"):
        changed = text.replace("https://eu.openrouter.ai/api/v1", f"https://{host}/api/v1")
        assert f"openrouter.base_url host '{host}' is not in allow_list.external_hosts" in (
            problems_for(tmp_path, changed)
        )


def test_placeholder_prices_warn_at_startup_with_metadata_only(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    catalogue.warn_placeholder_prices(settings)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["event"], r["level"], r["model"]) for r in lines] == [
        ("config.price_placeholder", "warning", e.id) for e in settings.models.catalogue
    ]
    for record in lines:
        assert set(record) == {"ts", "level", "event", "model"}


def test_real_prices_do_not_warn(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    real = [e.model_copy(update={"price_placeholder": False}) for e in settings.models.catalogue]
    models = settings.models.model_copy(update={"catalogue": tuple(real)})
    priced = dataclasses.replace(settings, models=models)
    capsys.readouterr()
    catalogue.warn_placeholder_prices(priced)
    assert capsys.readouterr().out == ""


def test_openrouter_config_loads(tmp_path: Path) -> None:
    env = {**ENV, "OPENROUTER_API_KEY": "test-openrouter-key"}
    settings = load_settings(environ=env, config_dir=write_config(tmp_path, OPENROUTER_TOML))
    assert settings.secrets.openrouter_api_key is not None
    assert [e.id for e in settings.models.catalogue if e.external] == [CLAUDE]


def test_startup_rejects_an_unlisted_external_host(tmp_path: Path) -> None:
    text = OPENROUTER_TOML.replace("https://eu.openrouter.ai/api/v1", "https://or.example/v1")
    assert problems_for(tmp_path, text) == [
        "openrouter.base_url host 'or.example' is not in allow_list.external_hosts"
    ]


def test_startup_rejects_openrouter_on_the_eu_list(tmp_path: Path) -> None:
    # An external provider listed as EU would slip past the entitlement: refused.
    text = OPENROUTER_TOML.replace(
        'external_hosts = ["eu.openrouter.ai"]', "external_hosts = []"
    ).replace('"api.scaleway.ai", "ragflow"]', '"api.scaleway.ai", "ragflow", "eu.openrouter.ai"]')
    assert problems_for(tmp_path, text) == [
        "openrouter.base_url host 'eu.openrouter.ai' is not in allow_list.external_hosts"
    ]


def test_startup_rejects_an_eu_service_on_an_external_host(tmp_path: Path) -> None:
    text = OPENROUTER_TOML.replace(
        'eu_hosts = ["api.mistral.ai", "api.scaleway.ai", "ragflow"]',
        'eu_hosts = ["api.mistral.ai", "ragflow"]',
    ).replace(
        'external_hosts = ["eu.openrouter.ai"]',
        'external_hosts = ["eu.openrouter.ai", "api.scaleway.ai"]',
    )
    assert problems_for(tmp_path, text) == [
        "scaleway.base_url host 'api.scaleway.ai' is not in allow_list.eu_hosts"
    ]


def test_startup_rejects_a_host_on_both_lists(tmp_path: Path) -> None:
    text = OPENROUTER_TOML.replace(
        'external_hosts = ["eu.openrouter.ai"]',
        'external_hosts = ["eu.openrouter.ai", "ragflow"]',
    )
    assert problems_for(tmp_path, text) == [
        "allow_list host 'ragflow' is in both eu_hosts and external_hosts"
    ]


async def test_app_refuses_to_start_with_an_unlisted_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import config

    text = OPENROUTER_TOML.replace("https://eu.openrouter.ai/api/v1", "https://or.example/v1")
    monkeypatch.setenv("ASK_SPORE_CONFIG_DIR", str(write_config(tmp_path, text)))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()
    app = create_app()
    try:
        with pytest.raises(ConfigError, match=r"not in allow_list\.external_hosts"):
            async with app.router.lifespan_context(app):
                pass
    finally:
        config.get_settings.cache_clear()


@pytest.mark.parametrize(
    "slug", ["anthropic/claude-latest", "anthropic/claude-opus-5.5:online", "openrouter/auto"]
)
def test_openrouter_slugs_must_be_pinned(tmp_path: Path, slug: str) -> None:
    text = OPENROUTER_TOML.replace(
        'models = ["anthropic/claude-opus-5.5"]',
        f'models = ["anthropic/claude-opus-5.5", "{slug}"]',
    )
    [problem] = problems_for(tmp_path, text)
    assert problem.startswith(f"openrouter.models '{slug}' must be a pinned")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            ("external = true", "external = false"),
            "catalogue 'anthropic/claude-opus-5.5': external must be true for provider "
            "'openrouter'",
        ),
        (
            ('reasoning = "effort"', 'reasoning = "thinking"'),
            "catalogue 'anthropic/claude-opus-5.5': reasoning switch 'thinking' is not "
            "offered by 'openrouter'",
        ),
        (
            ('id = "anthropic/claude-opus-5.5"', 'id = "anthropic/claude-opus-9"'),
            "catalogue 'anthropic/claude-opus-9' is not pinned in [openrouter]",
        ),
    ],
)
def test_catalogue_entries_are_checked(
    tmp_path: Path, change: tuple[str, str], expected: str
) -> None:
    head, tail = OPENROUTER_TOML.rsplit("[[catalogue]]", 1)
    text = head + "[[catalogue]]" + tail.replace(*change)
    assert problems_for(tmp_path, text) == [expected]


def test_catalogue_needs_the_default_model(tmp_path: Path) -> None:
    text = SCALEWAY_TOML.replace(
        'rewrite_model = "deepseek-v4.1-flash"', 'rewrite_model = "qwen3.8-27b"'
    ).replace('models = ["deepseek-v4.1-flash"]', 'models = ["deepseek-v4.1-flash", "qwen3.8-27b"]')
    assert problems_for(tmp_path, text) == ["default model 'qwen3.8-27b' is not in the catalogue"]


def test_openrouter_entry_needs_its_section(tmp_path: Path) -> None:
    text = OPENROUTER_TOML.replace(
        '[openrouter]\nbase_url = "https://eu.openrouter.ai/api/v1"\n'
        'models = ["anthropic/claude-opus-5.5"]\ntimeout_seconds = 30\n',
        "",
    )
    assert problems_for(tmp_path, text) == [
        "catalogue 'anthropic/claude-opus-5.5': provider 'openrouter' has no [openrouter] section"
    ]


def test_cost_is_priced_from_the_catalogue(settings: Settings) -> None:
    claude = entry(settings, CLAUDE)
    assert claude is not None
    price_in, price_out = claude.price_in_cents_per_mtok, claude.price_out_cents_per_mtok
    assert float(cost_cents(claude, 1_000_000, 0)) == price_in
    assert float(cost_cents(claude, 2000, 1000)) == pytest.approx(
        (2000 * price_in + 1000 * price_out) / 1_000_000
    )


# --- the entitlement check (no I/O) -------------------------------------------------------


def ent(*models: str, external: bool = False) -> ModelEntitlement:
    return ModelEntitlement(tuple(models), external, 1000 if external else None)


def test_enabled_eu_model_passes(settings: Settings) -> None:
    assert check_choice(settings, ent(DEEPSEEK, QWEN), ModelChoice(QWEN, True)).id == QWEN


@pytest.mark.parametrize(
    ("entitlement", "choice", "code"),
    [
        (ent(DEEPSEEK), ModelChoice(QWEN, False), "model_not_enabled"),
        (ent(DEEPSEEK, CLAUDE), ModelChoice(CLAUDE, False), "external_not_entitled"),
        (ent(DEEPSEEK, external=True), ModelChoice(CLAUDE, False), "model_not_enabled"),
        (ent(DEEPSEEK, "gone-model"), ModelChoice("gone-model", False), "model_unavailable"),
        (ent(), ModelChoice(DEEPSEEK, False), "model_not_enabled"),
    ],
)
def test_refusals(
    settings: Settings, entitlement: ModelEntitlement, choice: ModelChoice, code: str
) -> None:
    with pytest.raises(ModelRefused) as excinfo:
        check_choice(settings, entitlement, choice)
    assert excinfo.value.code == code


def test_eu_fallback_is_never_external(settings: Settings) -> None:
    # Sorted, "anthropic/..." comes first; the default must still be an EU model.
    both = ent(CLAUDE, GPT, QWEN, external=True)
    assert eu_fallback_choice(settings, both) == ModelChoice(QWEN, False)
    assert eu_fallback_choice(settings, ent(CLAUDE, DEEPSEEK, QWEN, external=True)) == (
        ModelChoice(DEEPSEEK, False)
    )
    assert eu_fallback_choice(settings, ent(CLAUDE, external=True)) is None


def test_usable_models_hide_external_without_entitlement(settings: Settings) -> None:
    assert [e.id for e in usable_models(settings, ent(CLAUDE, DEEPSEEK))] == [DEEPSEEK]
    assert [e.id for e in usable_models(settings, ent(CLAUDE, DEEPSEEK, external=True))] == [
        DEEPSEEK,
        CLAUDE,
    ]


# --- fail closed before any outbound call (orchestrator, PostgreSQL) ----------------------


@pytest.fixture
async def internal_entitlement(admin_conn: asyncpg.Connection) -> AsyncIterator[Any]:
    """Change the internal tenant's model entitlement for one test, then restore it."""
    saved = await admin_conn.fetchrow(
        "SELECT enabled_models, external_models_enabled, external_spend_cap_cents, "
        "external_acceptance_reference, external_acceptance_date "
        "FROM tenant_entitlements WHERE tenant_id = $1",
        INTERNAL_TENANT_ID,
    )

    async def set_(models: list[str], *, external: bool = False, cap: int | None = None) -> None:
        await admin_conn.execute(
            "UPDATE tenant_entitlements SET enabled_models = $2, external_models_enabled = $3, "
            "external_spend_cap_cents = $4, external_acceptance_reference = $5, "
            "external_acceptance_date = $6 WHERE tenant_id = $1",
            INTERNAL_TENANT_ID,
            models,
            external,
            cap,
            "Synthetic DPA v1" if external else None,
            date(2026, 10, 1) if external else None,
        )

    yield set_
    await admin_conn.execute(
        "UPDATE tenant_entitlements SET enabled_models = $2, external_models_enabled = $3, "
        "external_spend_cap_cents = $4, external_acceptance_reference = $5, "
        "external_acceptance_date = $6 WHERE tenant_id = $1",
        INTERNAL_TENANT_ID,
        *saved.values(),
    )


async def fixed_choice(world: World, choice: ModelChoice) -> None:
    """The conversation's model and reasoning (P1a-04's columns), set as the owner."""
    await world.fix_choice(choice.model, choice.reasoning)


async def _refused(
    settings: Settings, engine: AsyncEngine, world: World, recorder: Recorder
) -> tuple[list[Any], FakeRetriever]:
    retriever = FakeRetriever(chunks_for(world))
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=retriever,
        llm=router(settings, recorder),
    )
    # A follow-up: without the check, the rewrite call would go out first.
    await world.admin.execute(
        "INSERT INTO messages (tenant_id, conversation_id, role, content) "
        "VALUES ($1, $2, 'user', 'Earlier synthetic question?')",
        INTERNAL_TENANT_ID,
        world.conversation_id,
    )
    stream = await orch.answer(world.ctx, world.conversation_id, "And in 2025?")
    return [event async for event in stream], retriever


@pytest.mark.parametrize(
    ("models", "external", "choice", "code"),
    [
        ([DEEPSEEK], False, ModelChoice(QWEN, False), "model_not_enabled"),
        ([DEEPSEEK, CLAUDE], False, ModelChoice(CLAUDE, False), "external_not_entitled"),
    ],
)
async def test_refused_model_makes_no_outbound_call(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    internal_entitlement: Any,
    models: list[str],
    external: bool,
    choice: ModelChoice,
    code: str,
) -> None:
    await internal_entitlement(models, external=external)
    await fixed_choice(world, choice)
    recorder = Recorder()  # no replies: any request would fail the test
    events, retriever = await _refused(settings, engine, world, recorder)

    assert events == [ErrorEvent(code)]
    assert recorder.requests == []
    assert retriever.calls == []
    audit = await world.admin.fetchrow(
        "SELECT metadata FROM audit_events WHERE event = 'chat.query' "
        "AND metadata->>'conversation_id' = $1 ORDER BY created_at DESC LIMIT 1",
        str(world.conversation_id),
    )
    assert audit is not None
    metadata = json.loads(audit["metadata"])
    assert (metadata["error_code"], metadata["model"]) == (code, choice.model)


async def test_tenant_without_enabled_models_fails_closed(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([CLAUDE])  # only an external model, no entitlement
    recorder = Recorder()
    events, retriever = await _refused(settings, engine, world, recorder)
    assert events == [ErrorEvent("model_not_enabled")]
    assert recorder.requests == [] and retriever.calls == []


# --- GET /api/v1/models -------------------------------------------------------------------


async def test_models_route_lists_usable_models_with_external_flag(
    api: Harness, internal_entitlement: Any
) -> None:
    await internal_entitlement([CLAUDE, DEEPSEEK, QWEN])
    response = await api.request("GET", "/models")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": DEEPSEEK,
            "display_name": "DeepSeek V4.1 Flash",
            "external": False,
            "reasoning_switch": True,
            "default": True,
        },
        {
            "id": QWEN,
            "display_name": "Qwen 3.8 27B",
            "external": False,
            "reasoning_switch": True,
            "default": False,
        },
    ]
    await internal_entitlement([CLAUDE, QWEN], external=True, cap=10_000)
    listed = (await api.request("GET", "/models")).json()
    assert [(m["id"], m["external"], m["default"]) for m in listed] == [
        (QWEN, False, True),
        (CLAUDE, True, False),
    ]
