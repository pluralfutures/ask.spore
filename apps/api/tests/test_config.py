from pathlib import Path

import pytest

from app.core.config import DEFAULT_CONFIG_DIR, REQUIRED_SECRETS, ConfigError, load_settings
from app.main import create_app

VALID_TOML = """
[allow_list]
eu_hosts = ["api.mistral.ai", "ragflow"]

[mistral]
base_url = "https://api.mistral.ai"
chat_model = "mistral-large-2512"
rewrite_model = "mistral-small-2603"
timeout_seconds = 60

[ragflow]
base_url = "http://ragflow:9380"
timeout_seconds = 30
embedding_model = "BAAI/bge-m3@Builtin"

[prompts]
corpus_only = "v1"
general_knowledge = "v1"
rewrite = "v1"
judge = "v1"

[consent]
version = "v1"

[chat]
history_messages = 6
history_max_tokens = 2000
top_k = 10
similarity_threshold = 0.2
max_context_tokens = 6000
cache_ttl_seconds = 86400

[[catalogue]]
id = "mistral-large-2512"
provider = "mistral"
display_name = "Mistral Large"
reasoning = "none"
price_in_cents_per_mtok = 200
price_out_cents_per_mtok = 600
currency = "EUR"
external = false

[[catalogue]]
id = "mistral-small-2603"
provider = "mistral"
display_name = "Mistral Small"
reasoning = "none"
price_in_cents_per_mtok = 10
price_out_cents_per_mtok = 30
currency = "EUR"
external = false
"""

ENV = {
    "MISTRAL_API_KEY": "test-mistral-key",
    "SCALEWAY_API_KEY": "test-scaleway-key",
    "RAGFLOW_API_KEY": "test-ragflow-key",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "PHASE0_BEARER_TOKEN": "test-bearer-token-0123456789abcdef",
    "AUTHENTIK_CLIENT_SECRET": "test-authentik-client-secret",
    "AUTHENTIK_API_TOKEN": "test-authentik-api-token",
}


SYNTHETIC_NOTICE = (
    "# Synthetic notice\n\n## Summary\n\nSynthetic summary.\n\n"
    "## Full notice\n\nSynthetic notice text.\n"
)


def write_config(tmp_path: Path, text: str = VALID_TOML, *, prompts: bool = True) -> Path:
    (tmp_path / "models.toml").write_text(text, encoding="utf-8")
    if prompts:
        for name in ("corpus_only", "general_knowledge", "rewrite", "judge"):
            (tmp_path / "prompts" / name).mkdir(parents=True, exist_ok=True)
            (tmp_path / "prompts" / name / "v1.md").write_text("Synthetic prompt.\n")
        (tmp_path / "consent").mkdir(exist_ok=True)
        (tmp_path / "consent" / "v1.md").write_text(SYNTHETIC_NOTICE, encoding="utf-8")
    return tmp_path


def problems_for(tmp_path: Path, text: str, env: dict[str, str] | None = None) -> list[str]:
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV if env is None else env, config_dir=write_config(tmp_path, text))
    return excinfo.value.problems


def test_valid_config_loads(tmp_path: Path) -> None:
    settings = load_settings(environ=ENV, config_dir=write_config(tmp_path))
    assert settings.models.mistral.chat_model == "mistral-large-2512"
    assert settings.secrets.mistral_api_key.get_secret_value() == "test-mistral-key"


def test_repository_models_toml_is_valid() -> None:
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.models.allow_list.eu_hosts
    assert settings.models.allow_list.external_hosts == ("eu.openrouter.ai",)


def test_rejects_provider_host_not_in_allow_list(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "https://api.example.com")
    problems = problems_for(tmp_path, text)
    assert problems == ["mistral.base_url host 'api.example.com' is not in allow_list.eu_hosts"]


def test_rejects_ragflow_host_not_in_allow_list(tmp_path: Path) -> None:
    text = VALID_TOML.replace("http://ragflow:9380", "http://ragflow.example.com:9380")
    problems = problems_for(tmp_path, text)
    assert problems == ["ragflow.base_url host 'ragflow.example.com' is not in allow_list.eu_hosts"]


def test_allow_list_match_is_on_host_not_substring(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "https://api.mistral.ai.evil.example")
    assert any("not in allow_list.eu_hosts" in p for p in problems_for(tmp_path, text))


def test_rejects_plain_http_for_mistral(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "http://api.mistral.ai")
    assert problems_for(tmp_path, text) == ["mistral.base_url must use https"]


@pytest.mark.parametrize("alias", ["mistral-large-latest", "mistral-large", "mistral-large-2512x"])
def test_rejects_undated_model_alias(tmp_path: Path, alias: str) -> None:
    text = VALID_TOML.replace('"mistral-large-2512"', f'"{alias}"')
    problems = problems_for(tmp_path, text)
    assert len(problems) == 1
    assert problems[0].startswith(f"mistral.chat_model '{alias}' must be a dated version")


@pytest.mark.parametrize("name", REQUIRED_SECRETS)
def test_rejects_missing_secret(tmp_path: Path, name: str) -> None:
    env = {k: v for k, v in ENV.items() if k != name}
    assert problems_for(tmp_path, VALID_TOML, env) == [
        f"missing required secrets in the environment: {name}"
    ]


def test_rejects_blank_secret(tmp_path: Path) -> None:
    env = {**ENV, "RAGFLOW_API_KEY": "   "}
    assert problems_for(tmp_path, VALID_TOML, env) == [
        "missing required secrets in the environment: RAGFLOW_API_KEY"
    ]


def test_error_never_contains_secret_values(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "https://api.example.com")
    env = {k: v for k, v in ENV.items() if k != "REDIS_URL"}
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=env, config_dir=write_config(tmp_path, text))
    message = str(excinfo.value)
    for value in env.values():
        assert value not in message


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "http://api.example.com")
    problems = problems_for(tmp_path, text, {})
    assert len(problems) == 3


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    text = VALID_TOML + '\n[mistral_extra]\nbase_url = "https://anywhere.example"\n'
    assert any("mistral_extra" in p for p in problems_for(tmp_path, text))


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_settings(environ=ENV, config_dir=tmp_path)


async def test_app_refuses_to_start_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    for name in REQUIRED_SECRETS:
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    app = create_app()
    with pytest.raises(ConfigError, match="missing required secrets"):
        async with app.router.lifespan_context(app):
            pass
    config.get_settings.cache_clear()


def test_rejects_short_bearer_token(tmp_path: Path) -> None:
    env = {**ENV, "PHASE0_BEARER_TOKEN": "short"}
    assert problems_for(tmp_path, VALID_TOML, env) == [
        "PHASE0_BEARER_TOKEN must be at least 32 characters"
    ]


def test_rejects_latest_embedding_model(tmp_path: Path) -> None:
    text = VALID_TOML.replace("BAAI/bge-m3@Builtin", "mistral-embed-latest")
    assert problems_for(tmp_path, text) == [
        "ragflow.embedding_model must name a fixed model, not a '-latest' alias"
    ]


# --- LLM provider switch and Scaleway (findings M2) ---------------------------------------

SCALEWAY_TOML = (
    VALID_TOML.replace(
        'eu_hosts = ["api.mistral.ai", "ragflow"]',
        'eu_hosts = ["api.mistral.ai", "api.scaleway.ai", "ragflow"]',
    ).replace(
        "[ragflow]",
        """[llm]
provider = "scaleway"

[scaleway]
base_url = "https://api.scaleway.ai"
chat_model = "deepseek-v4.1-flash"
rewrite_model = "deepseek-v4.1-flash"
judge_model = "deepseek-v4.1-flash"
models = ["deepseek-v4.1-flash"]
timeout_seconds = 30
rate_limit_rps = 5
tokens_per_minute = 1000000

[ragflow]""",
    )
    + """
[[catalogue]]
id = "deepseek-v4.1-flash"
provider = "scaleway"
display_name = "DeepSeek V4.1 Flash"
reasoning = "thinking"
price_in_cents_per_mtok = 20
price_out_cents_per_mtok = 80
currency = "EUR"
external = false
"""
)
PROJECT = "0b8c5d3e-1f2a-4b6c-9d7e-8f9a0b1c2d3e"


def test_provider_defaults_to_mistral(tmp_path: Path) -> None:
    settings = load_settings(environ=ENV, config_dir=write_config(tmp_path))
    assert settings.models.llm.provider == "mistral"
    assert settings.models.scaleway is None


def test_scaleway_config_loads_with_undated_model_names(tmp_path: Path) -> None:
    env = {**ENV, "SCALEWAY_PROJECT_ID": PROJECT}
    settings = load_settings(environ=env, config_dir=write_config(tmp_path, SCALEWAY_TOML))
    assert settings.models.scaleway is not None
    assert settings.models.scaleway.chat_model == "deepseek-v4.1-flash"
    assert settings.models.scaleway.reasoning_effort == "none"
    assert settings.secrets.scaleway_api_key is not None
    assert settings.secrets.scaleway_project_id == PROJECT


@pytest.mark.parametrize(
    ("provider_toml", "missing", "unused"),
    [
        ("VALID", "MISTRAL_API_KEY", "SCALEWAY_API_KEY"),
        ("SCALEWAY", "SCALEWAY_API_KEY", "MISTRAL_API_KEY"),
    ],
)
def test_only_the_active_providers_key_is_required(
    tmp_path: Path, provider_toml: str, missing: str, unused: str
) -> None:
    text = VALID_TOML if provider_toml == "VALID" else SCALEWAY_TOML
    without_unused = {k: v for k, v in ENV.items() if k != unused}
    load_settings(environ=without_unused, config_dir=write_config(tmp_path, text))
    env = {k: v for k, v in ENV.items() if k != missing}
    assert problems_for(tmp_path, text, env) == [
        f"missing required secrets in the environment: {missing}"
    ]


@pytest.mark.parametrize("model", ["deepseek-latest", "deepseek-v4.1-flash-latest", "Deep Seek"])
def test_scaleway_rejects_alias_or_malformed_model_names(tmp_path: Path, model: str) -> None:
    text = SCALEWAY_TOML.replace('judge_model = "deepseek-v4.1-flash"', f'judge_model = "{model}"')
    [problem] = problems_for(tmp_path, text)
    assert problem.startswith(f"scaleway.judge_model '{model}' must be a fixed model name")


def test_scaleway_host_must_be_allow_listed_and_https(tmp_path: Path) -> None:
    text = SCALEWAY_TOML.replace(
        'base_url = "https://api.scaleway.ai"', 'base_url = "http://api.scaleway.example"'
    )
    assert sorted(problems_for(tmp_path, text)) == [
        "scaleway.base_url host 'api.scaleway.example' is not in allow_list.eu_hosts",
        "scaleway.base_url must use https",
    ]


def test_scaleway_provider_needs_its_section(tmp_path: Path) -> None:
    text = VALID_TOML.replace("[ragflow]", '[llm]\nprovider = "scaleway"\n\n[ragflow]')
    assert problems_for(tmp_path, text) == [
        "llm.provider is 'scaleway' but there is no [scaleway] section"
    ]


def test_scaleway_project_id_must_be_a_uuid(tmp_path: Path) -> None:
    env = {**ENV, "SCALEWAY_PROJECT_ID": "../../other"}
    assert problems_for(tmp_path, SCALEWAY_TOML, env) == [
        "SCALEWAY_PROJECT_ID must be a project UUID"
    ]


def test_repository_config_uses_scaleway_on_an_allow_listed_host() -> None:
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.models.llm.provider == "scaleway"
    assert settings.models.scaleway is not None
    assert "latest" not in settings.models.scaleway.chat_model


def test_ragflow_admin_ui_link_is_loopback_only(tmp_path: Path) -> None:
    # P1b-05: the content console's link to the private RAGFlow UI (over an SSH tunnel).
    base = 'embedding_model = "BAAI/bge-m3@Builtin"'
    ok = VALID_TOML.replace(base, base + '\nadmin_ui_url = "http://127.0.0.1:8080"')
    settings = load_settings(environ=ENV, config_dir=write_config(tmp_path, ok))
    assert settings.models.ragflow.admin_ui_url == "http://127.0.0.1:8080"
    for url in (
        "https://ragflow.example.com",
        "http://ragflow:80",
        "http://0.0.0.0:8080",
        "http://127.0.0.1:8080/admin",
    ):
        text = VALID_TOML.replace(base, base + f'\nadmin_ui_url = "{url}"')
        assert [p for p in problems_for(tmp_path, text) if "admin_ui_url" in p], url
    bad_path = VALID_TOML.replace(
        base, base + '\nadmin_ui_document_path = "https://x/{dataset_id}"'
    )
    assert problems_for(tmp_path, bad_path) == [
        "ragflow.admin_ui_document_path must be a path with {dataset_id}"
    ]


def test_repository_ragflow_admin_ui_is_on_the_loopback() -> None:
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.models.ragflow.admin_ui_url == "http://127.0.0.1:8080"


# --- deploy version (P1b-13 e) ------------------------------------------------------------


def test_deploy_version_comes_from_the_environment(tmp_path: Path) -> None:
    env = {**ENV, "ASK_SPORE_DEPLOY_VERSION": "0f3e244a1b2c"}
    assert load_settings(environ=env, config_dir=write_config(tmp_path)).deploy_version == (
        "0f3e244a1b2c"
    )


def test_deploy_version_falls_back_to_a_hash_of_the_config(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    first = load_settings(environ=ENV, config_dir=config).deploy_version
    assert first.startswith("files-")
    assert load_settings(environ=ENV, config_dir=config).deploy_version == first
    (config / "prompts" / "corpus_only" / "v1.md").write_text("Changed prompt.\n")
    assert load_settings(environ=ENV, config_dir=config).deploy_version != first


def test_rejects_a_malformed_deploy_version(tmp_path: Path) -> None:
    problems = problems_for(tmp_path, VALID_TOML, {**ENV, "ASK_SPORE_DEPLOY_VERSION": "a b;c"})
    assert any("ASK_SPORE_DEPLOY_VERSION" in p for p in problems)
