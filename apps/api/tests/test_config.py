from pathlib import Path

import pytest

from app.core.config import DEFAULT_CONFIG_DIR, REQUIRED_SECRETS, ConfigError, load_settings
from app.main import create_app

VALID_TOML = """
[allow_list]
hosts = ["api.mistral.ai", "ragflow"]

[mistral]
base_url = "https://api.mistral.ai"
chat_model = "mistral-large-2512"
rewrite_model = "mistral-small-2603"
timeout_seconds = 60

[ragflow]
base_url = "http://ragflow:9380"
timeout_seconds = 30
embedding_model = "BAAI/bge-m3@Builtin"
"""

ENV = {
    "MISTRAL_API_KEY": "test-mistral-key",
    "RAGFLOW_API_KEY": "test-ragflow-key",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "PHASE0_BEARER_TOKEN": "test-bearer-token-0123456789abcdef",
}


def write_config(tmp_path: Path, text: str = VALID_TOML) -> Path:
    (tmp_path / "models.toml").write_text(text, encoding="utf-8")
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
    assert settings.models.allow_list.hosts


def test_rejects_provider_host_not_in_allow_list(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "https://api.example.com")
    problems = problems_for(tmp_path, text)
    assert problems == ["mistral.base_url host 'api.example.com' is not in allow_list.hosts"]


def test_rejects_ragflow_host_not_in_allow_list(tmp_path: Path) -> None:
    text = VALID_TOML.replace("http://ragflow:9380", "http://ragflow.example.com:9380")
    problems = problems_for(tmp_path, text)
    assert problems == ["ragflow.base_url host 'ragflow.example.com' is not in allow_list.hosts"]


def test_allow_list_match_is_on_host_not_substring(tmp_path: Path) -> None:
    text = VALID_TOML.replace("https://api.mistral.ai", "https://api.mistral.ai.evil.example")
    assert any("not in allow_list.hosts" in p for p in problems_for(tmp_path, text))


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
