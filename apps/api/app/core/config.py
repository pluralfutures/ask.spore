"""Configuration: config/models.toml plus secrets from the environment.

Startup checks (design/Stack Decision.md, Conventions):

- every outbound host must be in the allow-list, which is split (P1a-09) into EU hosts
  (Mistral, Scaleway, RAGFlow, Authentik) and external hosts (OpenRouter, architecture
  §14.2): an EU service on an external host, or OpenRouter on an EU-listed host, is
  refused, and no host may be on both lists;
- public providers must be reached over HTTPS;
- model names must be dated versions, never "-latest" aliases (Scaleway names are not
  dated: they must only be fixed names, never containing "latest"; findings M2;
  OpenRouter slugs are fixed ``vendor/model`` names without a routing variant);
- the model catalogue (``[[catalogue]]``, P1a-09) lists only models its provider's
  section pins; a model is external exactly when its provider's host is an external
  host; the active provider's chat and rewrite models are in it (they are the platform
  default and are never external);
- every required secret must be present in the environment, including those of the
  authentication mode (``[auth] mode``: the Phase 0 bearer token, or Authentik's);
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
# key (PROVIDER_SECRETS) and the authentication mode's (AUTH_SECRETS).
REQUIRED_SECRETS: tuple[str, ...] = (
    "RAGFLOW_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
)
PROVIDER_SECRETS: dict[str, str] = {"mistral": "MISTRAL_API_KEY", "scaleway": "SCALEWAY_API_KEY"}
# Optional (P1a-10): without it no OpenRouter client is built and every external model
# is refused as unavailable (fail closed), so an Instance can run before the OpenRouter
# account and paperwork (P1a-15) exist.
OPENROUTER_SECRET = "OPENROUTER_API_KEY"  # noqa: S105 - the variable name, not a value
AUTH_SECRETS: dict[str, tuple[str, ...]] = {
    # Phase 0 shared token (P0-06), kept for the eval harness until Authentik replaces it.
    "phase0": ("PHASE0_BEARER_TOKEN",),
    # P1a-02: the API's confidential OIDC client, and an API token to provision users.
    "oidc": ("AUTHENTIK_CLIENT_SECRET", "AUTHENTIK_API_TOKEN"),
}
MIN_BEARER_TOKEN_LENGTH = 32
# Optional: Scaleway project to bill; it becomes part of the base URL path.
SCALEWAY_PROJECT_ENV = "SCALEWAY_PROJECT_ID"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Dated model versions such as "mistral-large-2512"; rejects "-latest" and other aliases.
_DATED_MODEL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}$")
# Scaleway serves undated names such as "deepseek-v4.1-flash" (findings M2).
_FIXED_MODEL = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
# OpenRouter slugs: "vendor/model", fixed names. No ":variant" suffix (":online" adds web
# search, ":free" changes the upstream terms) and no "openrouter/..." meta-router, which
# picks an arbitrary model.
_OPENROUTER_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9]+(?:[.-][a-z0-9]+)*$")


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
    """Outbound hosts (P1a-09). EU hosts carry every service; external hosts carry only
    external (non-EU) model providers, reachable for entitled tenants only."""

    eu_hosts: tuple[str, ...] = Field(min_length=1)
    external_hosts: tuple[str, ...] = ()


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
    # Every model the catalogue may offer on Scaleway (P1a-09); fixed names only.
    models: tuple[str, ...] = ()
    timeout_seconds: float = Field(gt=0)
    # DeepSeek reasons by default; "none" turns it off (findings M2). Sent as reasoning_effort.
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    judge_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    # Client-side throttle (app.llm.ratelimit), per process, below the account's limits.
    rate_limit_rps: float = Field(gt=0)
    tokens_per_minute: int = Field(gt=0)


class OpenRouterConfig(_Strict):
    """OpenRouter (OpenAI-compatible), an external host (P1a-10, architecture §14.2)."""

    base_url: str
    # Pinned slugs this account may call; the catalogue describes them.
    models: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)


ReasoningSwitch = Literal["thinking", "effort", "none"]
Provider = Literal["mistral", "scaleway", "openrouter"]
# Which reasoning switch each provider's API offers (app.llm.reasoning).
PROVIDER_SWITCHES: dict[str, frozenset[str]] = {
    "mistral": frozenset({"none"}),
    "scaleway": frozenset({"thinking", "none"}),
    "openrouter": frozenset({"effort", "none"}),
}


class CatalogueEntry(_Strict):
    """One model the operator may enable for a tenant (P1a-09)."""

    id: str = Field(min_length=1)
    provider: Provider
    display_name: str = Field(min_length=1, max_length=64)
    # "thinking": DeepSeek and Qwen thinking on or off; "effort": GPT and Claude
    # reasoning effort medium or none; "none": no switch, reasoning is always off.
    reasoning: ReasoningSwitch
    # Prices in euro cents per million tokens, used for the usage ledger and the
    # external spend cap (P1a-10).
    price_in_cents_per_mtok: float = Field(ge=0)
    price_out_cents_per_mtok: float = Field(ge=0)
    # Served outside the EU (compliance addendum, Oct 18 and 19, 2026); shown to users.
    external: bool


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


class AuthentikConfig(_Strict):
    """Authentik (P1a-02), reached by the API on the Compose network only."""

    base_url: str
    # The tokens' "iss": Authentik derives it from the host the API calls it on.
    issuer: str
    client_id: str = Field(min_length=1)
    # Registered on the provider for the authorization-code exchange. The API reads the
    # code from Authentik's redirect itself; no browser is ever sent there.
    redirect_uri: str
    sign_in_flow: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    timeout_seconds: float = Field(gt=0)


class AuthConfig(_Strict):
    """``phase0``: shared bearer token + X-User-Email (eval harness). ``oidc``: Authentik."""

    mode: Literal["phase0", "oidc"] = "phase0"
    # Sign-in links: single use, at most 15 minutes (architecture §4.3, §8).
    link_ttl_seconds: int = Field(default=900, ge=60, le=900)
    # At most this many links per user per link lifetime; further requests send nothing.
    links_per_window: int = Field(default=5, ge=1, le=20)
    authentik: AuthentikConfig | None = None


class ModelsConfig(_Strict):
    allow_list: AllowList
    auth: AuthConfig = AuthConfig()
    llm: LlmConfig = LlmConfig()
    mistral: MistralConfig
    scaleway: ScalewayConfig | None = None
    openrouter: OpenRouterConfig | None = None
    catalogue: tuple[CatalogueEntry, ...] = Field(min_length=1)
    ragflow: RagflowConfig
    prompts: PromptsConfig
    chat: ChatConfig


@dataclass(frozen=True)
class Secrets:
    mistral_api_key: SecretStr | None  # set when the provider is mistral
    ragflow_api_key: SecretStr
    database_url: SecretStr
    redis_url: SecretStr
    phase0_bearer_token: SecretStr | None  # set in auth mode "phase0"
    scaleway_api_key: SecretStr | None = None  # set when the provider is scaleway
    scaleway_project_id: str | None = None
    authentik_client_secret: SecretStr | None = None  # set in auth mode "oidc"
    authentik_api_token: SecretStr | None = None  # set in auth mode "oidc"
    openrouter_api_key: SecretStr | None = None  # optional; external models need it


@dataclass(frozen=True)
class Settings:
    models: ModelsConfig
    secrets: Secrets
    config_dir: Path


def _host(url: str) -> str | None:
    return urlsplit(url).hostname


def _check_hosts(
    problems: list[str], urls: dict[str, str], allowed: set[str], list_name: str
) -> None:
    for name, url in urls.items():
        host = _host(url)
        if host is None:
            problems.append(f"{name} is not a valid URL")
        elif host.lower() not in allowed:
            problems.append(f"{name} host '{host}' is not in allow_list.{list_name}")


def provider_models(models: ModelsConfig) -> dict[str, tuple[str, ...]]:
    """The model names each configured provider section pins."""
    pinned: dict[str, tuple[str, ...]] = {
        "mistral": (models.mistral.chat_model, models.mistral.rewrite_model)
    }
    if models.scaleway is not None:
        pinned["scaleway"] = models.scaleway.models
    if models.openrouter is not None:
        pinned["openrouter"] = models.openrouter.models
    return pinned


def default_models(models: ModelsConfig) -> tuple[str, str]:
    """The active provider's (chat, rewrite) models: the platform default (EU)."""
    if models.llm.provider == "scaleway" and models.scaleway is not None:
        return models.scaleway.chat_model, models.scaleway.rewrite_model
    return models.mistral.chat_model, models.mistral.rewrite_model


def _check_catalogue(models: ModelsConfig) -> list[str]:
    problems: list[str] = []
    pinned = provider_models(models)
    seen: set[str] = set()
    for entry in models.catalogue:
        where = f"catalogue '{entry.id}'"
        if entry.id in seen:
            problems.append(f"{where} is listed twice")
        seen.add(entry.id)
        if entry.provider not in pinned:
            problems.append(
                f"{where}: provider '{entry.provider}' has no [{entry.provider}] section"
            )
        elif entry.id not in pinned[entry.provider]:
            problems.append(f"{where} is not pinned in [{entry.provider}]")
        if entry.external != (entry.provider == "openrouter"):
            problems.append(
                f"{where}: external must be {str(entry.provider == 'openrouter').lower()} "
                f"for provider '{entry.provider}'"
            )
        if entry.reasoning not in PROVIDER_SWITCHES[entry.provider]:
            problems.append(
                f"{where}: reasoning switch '{entry.reasoning}' is not offered by "
                f"'{entry.provider}'"
            )
    for model in dict.fromkeys(default_models(models)):
        if model not in seen:
            problems.append(f"default model '{model}' is not in the catalogue")
    return problems


def _check_models(models: ModelsConfig) -> list[str]:
    problems: list[str] = []
    eu = {host.lower() for host in models.allow_list.eu_hosts}
    external = {host.lower() for host in models.allow_list.external_hosts}
    for host in sorted(eu & external):
        problems.append(f"allow_list host '{host}' is in both eu_hosts and external_hosts")

    eu_outbound = {
        "mistral.base_url": models.mistral.base_url,
        "ragflow.base_url": models.ragflow.base_url,
    }
    if models.scaleway is not None:
        eu_outbound["scaleway.base_url"] = models.scaleway.base_url
        if urlsplit(models.scaleway.base_url).scheme != "https":
            problems.append("scaleway.base_url must use https")
        fields = [
            (f"scaleway.{field}", getattr(models.scaleway, field))
            for field in ("chat_model", "rewrite_model", "judge_model")
        ] + [("scaleway.models", model) for model in models.scaleway.models]
        for name, model in fields:
            if "latest" in model.lower() or not _FIXED_MODEL.fullmatch(model):
                problems.append(
                    f"{name} '{model}' must be a fixed model name, not an alias like '-latest'"
                )
    elif models.llm.provider == "scaleway":
        problems.append("llm.provider is 'scaleway' but there is no [scaleway] section")
    if models.openrouter is not None:
        _check_hosts(
            problems,
            {"openrouter.base_url": models.openrouter.base_url},
            external,
            "external_hosts",
        )
        if urlsplit(models.openrouter.base_url).scheme != "https":
            problems.append("openrouter.base_url must use https")
        for slug in models.openrouter.models:
            if (
                "latest" in slug.lower()
                or slug.startswith("openrouter/")
                or not _OPENROUTER_SLUG.fullmatch(slug)
            ):
                problems.append(
                    f"openrouter.models '{slug}' must be a pinned 'vendor/model' slug, "
                    "not an alias, a ':variant' or the openrouter router"
                )

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
    if models.auth.authentik is not None:
        eu_outbound["auth.authentik.base_url"] = models.auth.authentik.base_url
        eu_outbound["auth.authentik.issuer"] = models.auth.authentik.issuer
    elif models.auth.mode == "oidc":
        problems.append("auth.mode is 'oidc' but there is no [auth.authentik] section")
    _check_hosts(problems, eu_outbound, eu, "eu_hosts")
    if "latest" in models.ragflow.embedding_model.lower():
        problems.append("ragflow.embedding_model must name a fixed model, not a '-latest' alias")
    return problems + _check_catalogue(models)


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
    auth_mode = models.auth.mode if models is not None else None
    required = [
        *REQUIRED_SECRETS,
        *([PROVIDER_SECRETS[provider]] if provider else []),
        *(AUTH_SECRETS[auth_mode] if auth_mode else ()),
    ]
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
        phase0_bearer_token=SecretStr(token) if auth_mode == "phase0" else None,
        scaleway_api_key=optional("SCALEWAY_API_KEY"),
        scaleway_project_id=project,
        authentik_client_secret=optional("AUTHENTIK_CLIENT_SECRET"),
        authentik_api_token=optional("AUTHENTIK_API_TOKEN"),
        openrouter_api_key=optional(OPENROUTER_SECRET),
    )
    return Settings(models=models, secrets=secrets, config_dir=directory)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, loaded once from the real environment."""
    return load_settings()
