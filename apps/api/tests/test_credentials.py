"""P1c-03: no deployment runs on a credential the repository publishes.

The API refuses to start in OIDC mode when a secret it reads (or a URL's password)
equals a value the ``.env.example`` files, the Compose defaults or CI publish; the host
script ``infra/scripts/check-credentials.py`` checks every ``.env`` file, including the
services the API never sees. Both report key names only, never a value.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, load_settings
from app.core.credentials import PUBLISHED_VALUES, published_credentials, url_password
from tests.test_config import ENV, write_config

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "infra" / "scripts" / "check-credentials.py"
APP_EXAMPLE_DSN = "postgresql+asyncpg://askspore_app:askspore-app-dev@postgres:5432/askspore"
OWNER_EXAMPLE_DSN = "postgresql+asyncpg://askspore:askspore-dev@postgres:5432/askspore"
ROTATED = "Synthetic-rotated-9f3c1e"


def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_credentials", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_credentials"] = module
    spec.loader.exec_module(module)
    return module


# --- the API's startup check ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DATABASE_URL", APP_EXAMPLE_DSN),
        ("MIGRATIONS_DATABASE_URL", OWNER_EXAMPLE_DSN),
        ("DATABASE_URL", "postgresql+asyncpg://askspore_app:askspore-app-dev@127.0.0.1/askspore"),
        ("REDIS_URL", "redis://:change-me@redis:6379/0"),
        ("AUTHENTIK_API_TOKEN", "ci-only-password"),
    ],
)
def test_the_api_refuses_to_start_on_a_published_credential(key: str, value: str) -> None:
    with pytest.raises(ConfigError) as refused:
        load_settings(environ={**ENV, key: value}, config_dir=DEFAULT_CONFIG_DIR)
    message = str(refused.value)
    assert key in message and "rotate" in message
    password = url_password(value) or value
    assert password not in message and value not in message


def test_every_published_key_is_named_at_once() -> None:
    env = {**ENV, "DATABASE_URL": APP_EXAMPLE_DSN, "MIGRATIONS_DATABASE_URL": OWNER_EXAMPLE_DSN}
    assert published_credentials(env) == ["DATABASE_URL", "MIGRATIONS_DATABASE_URL"]
    with pytest.raises(ConfigError, match="DATABASE_URL, MIGRATIONS_DATABASE_URL"):
        load_settings(environ=env, config_dir=DEFAULT_CONFIG_DIR)


def test_the_api_starts_on_rotated_credentials() -> None:
    env = {
        **ENV,
        "DATABASE_URL": APP_EXAMPLE_DSN.replace("askspore-app-dev", ROTATED),
        "MIGRATIONS_DATABASE_URL": OWNER_EXAMPLE_DSN.replace("askspore-dev", ROTATED + "-owner"),
        "REDIS_URL": "redis://redis:6379/0",  # no password: nothing published to match
    }
    settings = load_settings(environ=env, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.models.auth.mode == "oidc"


def test_a_password_that_merely_contains_a_published_one_passes() -> None:
    env = {**ENV, "DATABASE_URL": APP_EXAMPLE_DSN.replace("askspore-app-dev", "askspore-dev-x")}
    assert published_credentials(env) == []


def test_phase0_mode_keeps_the_local_stacks_working(tmp_path: Path) -> None:
    # The Phase 0 bearer-token mode is the loopback dev and eval stack; no user signs in.
    env = {**ENV, "DATABASE_URL": APP_EXAMPLE_DSN}
    settings = load_settings(environ=env, config_dir=write_config(tmp_path))
    assert settings.models.auth.mode == "phase0"


def test_the_published_values_are_what_the_repository_publishes() -> None:
    values, defaults = script().published(REPO)
    assert values == set(PUBLISHED_VALUES)
    assert defaults == {"POSTGRES_PASSWORD": "askspore-dev", "APP_DB_PASSWORD": "askspore-app-dev"}


# --- the host script ---------------------------------------------------------------------


@pytest.fixture
def host(tmp_path: Path) -> Path:
    """A repository root with the real examples, Compose files and CI workflow, and
    each .env a copy of its example (as on a fresh install)."""
    for name in (
        ".env.example",
        "infra/authentik/.env.example",
        "infra/ragflow/.env.example",
        "infra/compose.dev.yml",
        "infra/authentik/docker-compose.yml",
        ".github/workflows/ci.yml",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, tmp_path / name)
    for name in (".env", "infra/authentik/.env", "infra/ragflow/.env"):
        shutil.copy(tmp_path / f"{name}.example", tmp_path / name)
    return tmp_path


def rotate(path: Path, **values: str) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = [
        line
        for line in text.splitlines()
        if line.partition("=")[0] not in values
    ]
    path.write_text("\n".join([*lines, *(f"{k}={v}" for k, v in values.items())]) + "\n")


def test_the_script_fires_on_the_example_values(
    host: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = script()
    assert module.main(["--root", str(host)]) == 1
    out = capsys.readouterr().out
    for key in (
        ".env:DATABASE_URL",
        ".env:MIGRATIONS_DATABASE_URL",
        "infra/.env:POSTGRES_PASSWORD (unset",
        "infra/.env:APP_DB_PASSWORD (unset",
        "infra/ragflow/.env:ELASTIC_PASSWORD",
        "infra/ragflow/.env:MYSQL_PASSWORD",
        "infra/ragflow/.env:MINIO_PASSWORD",
        "infra/ragflow/.env:REDIS_PASSWORD",
    ):
        assert key in out, key
    for value in PUBLISHED_VALUES:
        assert value not in out


def test_the_script_passes_on_rotated_values(
    host: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("POSTGRES_PASSWORD", "APP_DB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    rotate(
        host / ".env",
        DATABASE_URL=APP_EXAMPLE_DSN.replace("askspore-app-dev", ROTATED + "-app"),
        MIGRATIONS_DATABASE_URL=OWNER_EXAMPLE_DSN.replace("askspore-dev", ROTATED + "-owner"),
    )
    rotate(
        host / "infra" / ".env",
        POSTGRES_PASSWORD=ROTATED + "-owner",
        APP_DB_PASSWORD=ROTATED + "-app",
    )
    rotate(
        host / "infra" / "ragflow" / ".env",
        ELASTIC_PASSWORD=ROTATED + "-es",
        MYSQL_PASSWORD=ROTATED + "-mysql",
        MINIO_PASSWORD=ROTATED + "-minio",
        REDIS_PASSWORD=ROTATED + "-redis",
    )
    assert script().main(["--root", str(host)]) == 0, capsys.readouterr().out
    assert ROTATED not in capsys.readouterr().out


def test_the_script_reads_compose_interpolation_from_the_shell_too(host: Path) -> None:
    module = script()
    shell = {"POSTGRES_PASSWORD": ROTATED, "APP_DB_PASSWORD": "askspore-app-dev"}
    failing = module.failing_keys(host, environ=shell)
    assert "infra/.env:APP_DB_PASSWORD" in failing
    assert not any(key.startswith("infra/.env:POSTGRES_PASSWORD") for key in failing)


def test_the_script_flags_authentik_bootstrap_keys(host: Path) -> None:
    rotate(host / "infra" / "authentik" / ".env", AUTHENTIK_BOOTSTRAP_TOKEN=ROTATED)
    failing = script().failing_keys(host, environ={})
    assert "infra/authentik/.env:AUTHENTIK_BOOTSTRAP_TOKEN (bootstrap)" in failing
