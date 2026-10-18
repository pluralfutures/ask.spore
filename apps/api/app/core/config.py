"""Configuration: config/models.toml plus secrets from the environment.

Startup checks (design/Stack Decision.md, Conventions):

- every outbound host (provider and RAGFlow base URLs) must be in the allow-list;
- public providers must be reached over HTTPS;
- model names must be dated versions, never "-latest" aliases (Scaleway names are not
  dated: they must only be fixed names, never containing "latest"; findings M2);
- every required secret must be present in the environment;
- every active prompt version must exist under ``prompts/`` in the config directory.

Any failure raises ConfigError listing every problem; the API does not start.
Error messages name the offending setting or variable, never a secret value.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

CONFIG_DIR_ENV = "ASK_SPORE_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"

# Environment variables that must be set and non-empty, plus the active LLM provider's
# key (PROVIDER_SECRETS).
REQUIRED_SECRETS: tuple[str, ...] = (
    "RAGFLOW_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "PHASE0_BEARER_TOKEN",  # Phase 0 only (P0-06); removed with Authentik in Phase 1
)
PROVIDER_SECRETS: dict[str, str] = {"mistral": "MISTRAL_API_KEY", "scaleway": "SCALEWAY_API_KEY"}
MIN_BEARER_TOKEN_LENGTH = 32
# Optional: Scaleway project to bill; it becomes part of the base URL path.
SCALEWAY_PROJECT_ENV = "SCALEWAY_PROJECT_ID"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Dated model versions such as "mistral-large-2512"; rejects "-latest" and other aliases.
_DATED_MODEL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}$")
# Scaleway serves undated names such as "deepseek-v4.1-flash" (findings M2).
_FIXED_MODEL = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


class ConfigError(RuntimeError):
    """Configuration is invalid; the API must not start."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            "Refusing to start, configuration is invalid:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AllowList(_Strict):
    hosts: tuple[str, ...] = Field(min_length=1)


class MistralConfig(_Strict):
    base_url: str
    chat_model: str
    rewrite_model: str
    timeout_seconds: float = Field(gt=0)


class LlmConfig(_Strict):
    """Which provider the API and the eval harness call (findings M2)."""

    provider: Literal["mistral", "scaleway"] = "mistral"


class ScalewayConfig(_Strict):
    """Scaleway Generative APIs (OpenAI-compatible), Paris. Names are not dated."""

    base_url: str
    chat_model: str
    rewrite_model: str
    judge_model: str
    timeout_seconds: float = Field(gt=0)
    # DeepSeek reasons by default; "none" turns it off (findings M2). Sent as reasoning_effort.
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    judge_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    # Client-side throttle (app.llm.ratelimit), per process, below the account's limits.
    rate_limit_rps: float = Field(gt=0)
    tokens_per_minute: int = Field(gt=0)


class RagflowConfig(_Strict):
    base_url: str
    timeout_seconds: float = Field(gt=0)
    # Embedding model new datasets are created with, as RAGFlow names it (P0-08).
    embedding_model: str = Field(min_length=1)


class PromptsConfig(_Strict):
    """Active prompt versions: ``prompts/<name>/<version>.md`` (app.chat.prompts)."""

    corpus_only: str = Field(pattern=r"^v[1-9][0-9]*$")
    rewrite: str = Field(pattern=r"^v[1-9][0-9]*$")
    # Faithfulness judge of the eval harness (P0-18); not used by the API itself.
    judge: str = Field(pattern=r"^v[1-9][0-9]*$")


class ChatConfig(_Strict):
    """Orchestrator parameters (P0-14). Token counts are estimates (~4 characters each)."""

    history_messages: int = Field(ge=0, le=50)
    history_max_tokens: int = Field(ge=0)
    top_k: int = Field(ge=1, le=100)
    similarity_threshold: float = Field(ge=0, le=1)
    max_context_tokens: int = Field(gt=0)
    # Answer cache TTL; app.core.cache caps every TTL at the 30-day retention limit.
    cache_ttl_seconds: int = Field(gt=0, le=30 * 24 * 3600)


class ModelsConfig(_Strict):
    allow_list: AllowList
    llm: LlmConfig = LlmConfig()
    mistral: MistralConfig
    scaleway: ScalewayConfig | None = None
    ragflow: RagflowConfig
    prompts: PromptsConfig
    chat: ChatConfig


@dataclass(frozen=True)
class Secrets:
    mistral_api_key: SecretStr | None  # set when the provider is mistral
    ragflow_api_key: SecretStr
    database_url: SecretStr
    redis_url: SecretStr
    phase0_bearer_token: SecretStr
    scaleway_api_key: SecretStr | None = None  # set when the provider is scaleway
    scaleway_project_id: str | None = None


@dataclass(frozen=True)
class Settings:
    models: ModelsConfig
    secrets: Secrets
    config_dir: Path


def _host(url: str) -> str | None:
    return urlsplit(url).hostname


def _check_models(models: ModelsConfig) -> list[str]:
    problems: list[str] = []
    allowed = {host.lower() for host in models.allow_list.hosts}

    outbound = {
        "mistral.base_url": models.mistral.base_url,
        "ragflow.base_url": models.ragflow.base_url,
    }
    if models.scaleway is not None:
        outbound["scaleway.base_url"] = models.scaleway.base_url
        if urlsplit(models.scaleway.base_url).scheme != "https":
            problems.append("scaleway.base_url must use https")
        for field in ("chat_model", "rewrite_model", "judge_model"):
            model = getattr(models.scaleway, field)
            if "latest" in model.lower() or not _FIXED_MODEL.fullmatch(model):
                problems.append(
                    f"scaleway.{field} '{model}' must be a fixed model name, "
                    "not an alias like '-latest'"
                )
    elif models.llm.provider == "scaleway":
        problems.append("llm.provider is 'scaleway' but there is no [scaleway] section")
    for name, url in outbound.items():
        host = _host(url)
        if host is None:
            problems.append(f"{name} is not a valid URL")
        elif host.lower() not in allowed:
            problems.append(f"{name} host '{host}' is not in allow_list.hosts")

    if urlsplit(models.mistral.base_url).scheme != "https":
        problems.append("mistral.base_url must use https")

    for name, model in {
        "mistral.chat_model": models.mistral.chat_model,
        "mistral.rewrite_model": models.mistral.rewrite_model,
    }.items():
        if not _DATED_MODEL.fullmatch(model):
            problems.append(
                f"{name} '{model}' must be a dated version such as 'mistral-large-2512', "
                "not an alias like '-latest'"
            )
    if "latest" in models.ragflow.embedding_model.lower():
        problems.append("ragflow.embedding_model must name a fixed model, not a '-latest' alias")
    return problems


def _check_prompts(prompts: PromptsConfig, directory: Path) -> list[str]:
    problems: list[str] = []
    for name, version in prompts.model_dump().items():
        path = directory / "prompts" / name / f"{version}.md"
        if not path.is_file():
            problems.append(f"prompts.{name} = '{version}' but {path} does not exist")
        elif not path.read_text(encoding="utf-8").strip():
            problems.append(f"prompts.{name}: {path} is empty")
    return problems


def _load_toml(path: Path) -> tuple[ModelsConfig | None, list[str]]:
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"config file not found: {path}"]
    except tomllib.TOMLDecodeError as exc:
        return None, [f"{path.name} is not valid TOML: {exc}"]
    try:
        return ModelsConfig.model_validate(raw), []
    except ValidationError as exc:
        return None, [
            f"{path.name}: {'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]


def load_settings(
    environ: Mapping[str, str] | None = None, config_dir: Path | None = None
) -> Settings:
    """Load and validate configuration; raise ConfigError on any problem."""
    env = os.environ if environ is None else environ
    directory = config_dir or Path(env.get(CONFIG_DIR_ENV) or DEFAULT_CONFIG_DIR)

    models, problems = _load_toml(directory / "models.toml")
    if models is not None:
        problems += _check_models(models)
        problems += _check_prompts(models.prompts, directory)

    provider = models.llm.provider if models is not None else None
    required = [*REQUIRED_SECRETS, *([PROVIDER_SECRETS[provider]] if provider else [])]
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        problems.append("missing required secrets in the environment: " + ", ".join(missing))
    token = env.get("PHASE0_BEARER_TOKEN", "").strip()
    if token and len(token) < MIN_BEARER_TOKEN_LENGTH:
        problems.append(
            f"PHASE0_BEARER_TOKEN must be at least {MIN_BEARER_TOKEN_LENGTH} characters"
        )

    project = env.get(SCALEWAY_PROJECT_ENV, "").strip() or None
    if project is not None and not _UUID.fullmatch(project):
        problems.append(f"{SCALEWAY_PROJECT_ENV} must be a project UUID")

    if problems or models is None:
        raise ConfigError(problems)

    def optional(name: str) -> SecretStr | None:
        value = env.get(name, "").strip()
        return SecretStr(value) if value else None

    secrets = Secrets(
        mistral_api_key=optional("MISTRAL_API_KEY"),
        ragflow_api_key=SecretStr(env["RAGFLOW_API_KEY"]),
        database_url=SecretStr(env["DATABASE_URL"]),
        redis_url=SecretStr(env["REDIS_URL"]),
        phase0_bearer_token=SecretStr(token),
        scaleway_api_key=optional("SCALEWAY_API_KEY"),
        scaleway_project_id=project,
    )
    return Settings(models=models, secrets=secrets, config_dir=directory)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, loaded once from the real environment."""
    return load_settings()
