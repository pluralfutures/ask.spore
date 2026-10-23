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
- a catalogue entry priced in USD needs ``[pricing] usd_to_eur``; an OpenRouter
  provider pin (``provider_order``, ``provider_only``) is allowed on OpenRouter entries
  only, with provider slugs;
- every required secret must be present in the environment, including those of the
  authentication mode (``[auth] mode``: the Phase 0 bearer token, or Authentik's);
- every active prompt version must exist under ``prompts/`` in the config directory;
- platform mail (``[mail]``, P1b-11): the active provider's section exists, every mail
  host is an EU host over HTTPS (Scaleway Transactional Email, and Mailgun's EU region
  only as the configured backup), and every active template version exists under
  ``mail/`` and renders with the fixed placeholders only.

Any failure raises ConfigError listing every problem; the API does not start.
Error messages name the offending setting or variable, never a secret value.
"""

from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.chat.prompts import check_slot
from app.consent.notice import check_notice
from app.core.credentials import published_credentials
from app.core.mailtemplates import TEMPLATE_NAMES, check_template

CONFIG_DIR_ENV = "ASK_SPORE_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
# P1b-13 (e), findings 1a F10: the deployed build, part of the answer cache key, so a
# deploy never serves answers cached by the previous code. Set by the Compose file from
# the deploy step (the git commit); without it, a hash of the configuration and code.
DEPLOY_VERSION_ENV = "ASK_SPORE_DEPLOY_VERSION"
APP_DIR = Path(__file__).resolve().parents[1]
_DEPLOY_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$")

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
# Platform mail (P1b-11), optional like OpenRouter's key: without the active provider's
# key no sender is built and every send_mail job fails with ``mail_not_configured``.
# A separate IAM key whose policy allows Transactional Email only (EmailSend on the
# project), not the Generative APIs key, whose policy does not cover it.
SCALEWAY_TEM_KEY_ENV = "SCALEWAY_TEM_API_KEY"
# The project the emails are sent from; SCALEWAY_PROJECT_ID when unset.
SCALEWAY_TEM_PROJECT_ENV = "SCALEWAY_TEM_PROJECT_ID"
MAILGUN_KEY_ENV = "MAILGUN_API_KEY"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Dated model versions such as "mistral-large-2512"; rejects "-latest" and other aliases.
_DATED_MODEL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}$")
# Scaleway serves undated names such as "deepseek-v4.1-flash" (findings M2).
_FIXED_MODEL = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
# OpenRouter slugs: "vendor/model", fixed names. No ":variant" suffix (":online" adds web
# search, ":free" changes the upstream terms) and no "openrouter/..." meta-router, which
# picks an arbitrary model.
_OPENROUTER_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9]+(?:[.-][a-z0-9]+)*$")
# OpenRouter provider slugs for a pin, such as "amazon-bedrock" or "azure".
_PROVIDER_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
    # P1b-17 (owner decision 2 of Oct 22, 2026): when the active provider fails to open
    # an answer (5xx, 429, timeout), the other EU provider answers instead (Stack
    # Decision, fallback LLM row). Needs that provider's section and key. Tenants with
    # the external-models entitlement may then fail over to OpenRouter as well.
    eu_failover: bool = False


class ScalewayConfig(_Strict):
    """Scaleway Generative APIs (OpenAI-compatible), Paris. Names are not dated."""

    base_url: str
    chat_model: str
    rewrite_model: str
    # Every model the catalogue may offer on Scaleway (P1a-09); fixed names only.
    models: tuple[str, ...] = ()
    timeout_seconds: float = Field(gt=0)
    # DeepSeek reasons by default; "none" turns it off (findings M2). Sent as reasoning_effort.
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
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
    # The effort sent when reasoning is on; models differ in what they accept (DeepSeek
    # V4.1 on Scaleway refuses "medium": low, high, xhigh or max; checked Oct 21, 2026).
    reasoning_effort_on: str = Field(default="medium", pattern=r"^[a-z]+$")
    # False: the switch exists (off is sent explicitly) but users cannot turn it on.
    # DeepSeek V4.1: reasoning length is unbounded on real questions (release, Oct 21,
    # 2026: 5 of 7 runs used 7,300 to 7,800 reasoning tokens at every effort tried).
    reasoning_on_offered: bool = True
    # Prices in cents of ``currency`` per million tokens, used for the usage ledger and
    # the external spend cap (P1a-10). The ledger prices in euro cents: USD entries are
    # converted at ``[pricing] usd_to_eur``, which startup requires when one exists.
    price_in_cents_per_mtok: float = Field(ge=0)
    price_out_cents_per_mtok: float = Field(ge=0)
    currency: Literal["EUR", "USD"]
    # Marks prices that are still placeholders, to be replaced from the provider's price
    # list; the API logs a warning per such entry at startup (none is set since Oct 19).
    price_placeholder: bool = False
    # OpenRouter provider pin (owner, Oct 19, 2026): ``provider_order`` is sent as
    # ``provider.order`` and ``provider_only`` as ``provider.allow_fallbacks = false``.
    # Zero-data-retention routing is applied after the pin (app.llm.openrouter).
    provider_order: tuple[str, ...] = ()
    provider_only: bool = False
    # Served outside the EU (compliance addendum, Oct 18 and 19, 2026); shown to users.
    external: bool

    @property
    def can_reason(self) -> bool:
        """Whether a conversation with this model may turn reasoning on."""
        return self.reasoning != "none" and self.reasoning_on_offered


class PricingConfig(_Strict):
    """Currency conversion for the usage ledger, which prices in euro cents (P1a-10)."""

    usd_to_eur: float | None = Field(default=None, gt=0)


class RagflowConfig(_Strict):
    base_url: str
    timeout_seconds: float = Field(gt=0)
    # Embedding model new datasets are created with, as RAGFlow names it (P0-08).
    embedding_model: str = Field(min_length=1)
    # P1b-05: the private RAGFlow web UI for chunk spot-checks, linked from the content
    # console. A loopback URL only (checked at startup): an operator reaches it over an
    # SSH tunnel to the Instance; it is never published or proxied by the API.
    admin_ui_url: str | None = None
    # Paths of a dataset and of one document's chunks in that UI (the pinned RAGFlow
    # version's routes, infra/ragflow/VERSION).
    admin_ui_dataset_path: str = "/dataset/dataset/{dataset_id}"
    admin_ui_document_path: str = "/chunk/parsed/chunks?id={dataset_id}&doc_id={document_id}"


class PromptsConfig(_Strict):
    """Active prompt versions: ``prompts/<name>/<version>.md`` (app.chat.prompts)."""

    corpus_only: str = Field(pattern=r"^v[1-9][0-9]*$")
    # The general-knowledge answer mode (P1a-06), for tenants entitled to it.
    general_knowledge: str = Field(pattern=r"^v[1-9][0-9]*$")
    rewrite: str = Field(pattern=r"^v[1-9][0-9]*$")
    # Faithfulness judge of the eval harness (P0-18); not used by the API itself.
    judge: str = Field(pattern=r"^v[1-9][0-9]*$")


class ConsentConfig(_Strict):
    """The use and privacy notice users must accept (P1b-10): ``consent/<version>.md``."""

    version: str = Field(pattern=r"^v[1-9][0-9]*$")


class ChatConfig(_Strict):
    """Orchestrator parameters (P0-14). Token counts are estimates (~4 characters each)."""

    history_messages: int = Field(ge=0, le=50)
    history_max_tokens: int = Field(ge=0)
    top_k: int = Field(ge=1, le=100)
    similarity_threshold: float = Field(ge=0, le=1)
    max_context_tokens: int = Field(gt=0)
    # RAGFlow's hybrid score weight (P1b-15 e); RAGFlow's default.
    vector_similarity_weight: float = Field(default=0.3, ge=0, le=1)
    # Answer cache TTL; app.core.cache caps every TTL at the 30-day retention limit.
    cache_ttl_seconds: int = Field(gt=0, le=30 * 24 * 3600)


class FilesConfig(_Strict):
    """Workspace file list and downloads (P1a-14)."""

    content_root: Path = Path("/srv/ask-spore/content")
    download_url_ttl_seconds: int = Field(default=60, ge=10, le=300)
    downloads_per_user_per_day: int = Field(default=50, ge=1, le=1000)


class EvalConfig(_Strict):
    """The eval harness's faithfulness judge (P1b-15 c), pinned on its own so that it can
    be a different model from the one whose answers it grades (findings D6). EU
    providers only: the judge sees corpus passages."""

    judge_provider: Literal["mistral", "scaleway"]
    judge_model: str = Field(min_length=1)
    judge_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"


class RetentionConfig(_Strict):
    """The retention purge (P1b-14). Chat history follows each tenant's setting (at most
    30 days, CLAUDE.md); this section sets only what has no tenant setting."""

    # Download records (who fetched which file when): owner decision of Oct 21, 2026
    # (90). At most a year (P1c-04, independent review of Oct 22, 2026: 3650 before).
    downloads_days: int = Field(default=90, ge=1, le=365)


_VERSION = r"^v[1-9][0-9]*$"


class ScalewayMailConfig(_Strict):
    """Scaleway Transactional Email, HTTP API (Stack Decision, email row)."""

    base_url: str
    api_version: str = Field(pattern=r"^v[0-9]+(?:alpha|beta)?[0-9]*$")
    region: Literal["fr-par"] = "fr-par"


class MailgunConfig(_Strict):
    """Mailgun, EU region only: the configured backup, used only while ``provider`` names
    it (after its DPA is filed)."""

    base_url: str
    api_version: Literal["v3"] = "v3"
    domain: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}$")


class MailTemplatesConfig(_Strict):
    """Active versions of ``mail/<name>/<version>.txt`` and ``.html`` (P1b-11)."""

    invitation: str = Field(pattern=_VERSION)
    spend_cap_80: str = Field(pattern=_VERSION)
    spend_cap_100: str = Field(pattern=_VERSION)
    tenant_name_flag: str = Field(pattern=_VERSION)
    consent_notice: str = Field(pattern=_VERSION)


class MailConfig(_Strict):
    """Platform transactional mail (P1b-11): exactly one provider sends at a time."""

    provider: Literal["scaleway", "mailgun"]
    from_address: str = Field(pattern=r"^[a-z0-9._+-]+@[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}$")
    from_name: str = Field(min_length=1, max_length=64)
    # Where recipients sign in; the only link a platform email carries.
    app_url: str = Field(pattern=r"^https://[a-z0-9.-]+$")
    timeout_seconds: float = Field(gt=0, le=60)
    scaleway: ScalewayMailConfig | None = None
    mailgun: MailgunConfig | None = None
    templates: MailTemplatesConfig


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
    # P1b-07: our public origin. Tenant SSO sources call back to it (Caddy hands those
    # paths to the API), so the API presents it as the Host when it relays a sign-in to
    # Authentik. Not an outbound host: nothing is ever sent to it by the API.
    public_url: str | None = Field(default=None, pattern=r"^https://[a-z0-9.-]+$")
    # The flows every tenant source uses (infra/authentik/blueprints): sign in a known
    # source user, or create one (JIT); both update the user from the source's mapping.
    source_authentication_flow: str = Field(
        default="ask-spore-source-authentication", pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    source_enrollment_flow: str = Field(
        default="ask-spore-source-enrollment", pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    source_pre_authentication_flow: str = Field(
        default="ask-spore-source-pre-authentication", pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    # P1b-08: the group the sign-in-link flow's authenticator validation stage is bound
    # to. The API keeps tenant admins of tenants that require a second factor in it.
    admin_mfa_group: str = Field(default="ask-spore-tenant-admins", pattern=r"^[a-z0-9][a-z0-9-]*$")


class EvalServiceConfig(_Strict):
    """P1b-15 a: the eval harness's signed service credential under ``mode = "oidc"``
    (``app.auth.eval_service``). Only the Ed25519 **public** key is here; the private key
    is the eval runner's secret. Absent from the production config."""

    email: str = Field(pattern=r"^[a-z0-9._+-]+@[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}$")
    public_key: str = Field(min_length=1)
    max_lifetime_seconds: int = Field(default=900, ge=60, le=3600)


class AuthConfig(_Strict):
    """``phase0``: shared bearer token + X-User-Email (eval harness). ``oidc``: Authentik."""

    mode: Literal["phase0", "oidc"] = "phase0"
    # Sign-in links: single use, at most 15 minutes (architecture §4.3, §8).
    link_ttl_seconds: int = Field(default=900, ge=60, le=900)
    # At most this many links per user per link lifetime; further requests send nothing.
    links_per_window: int = Field(default=5, ge=1, le=20)
    # P1b-08: per client IP, at most this many sign-in requests (link, discovery, SSO
    # start, each counted on its own) per window; more get 429 and nothing is sent.
    # Caddy's limit would be a second layer (findings 1b B11).
    ip_requests_per_window: int = Field(default=10, ge=1, le=1000)
    ip_window_seconds: int = Field(default=600, ge=60, le=3600)
    # P1b-08: how long the refresh cookie lives; matches the Authentik provider's
    # refresh_token_validity (infra/authentik/blueprints). The session is renewed before
    # the access token (8 hours) expires, at most this long after the last renewal.
    refresh_token_ttl_seconds: int = Field(default=86_400, ge=3_600, le=7 * 86_400)
    authentik: AuthentikConfig | None = None
    # P1b-15 a: accept the eval harness's signed credential (test and eval APIs only).
    eval_service: EvalServiceConfig | None = None


class ModelsConfig(_Strict):
    allow_list: AllowList
    auth: AuthConfig = AuthConfig()
    llm: LlmConfig = LlmConfig()
    mistral: MistralConfig
    scaleway: ScalewayConfig | None = None
    openrouter: OpenRouterConfig | None = None
    catalogue: tuple[CatalogueEntry, ...] = Field(min_length=1)
    pricing: PricingConfig = PricingConfig()
    ragflow: RagflowConfig
    prompts: PromptsConfig
    consent: ConsentConfig
    chat: ChatConfig
    files: FilesConfig = FilesConfig()
    retention: RetentionConfig = RetentionConfig()
    # The eval judge (P1b-15 c); without it the harness judges with the active provider's
    # chat model.
    eval: EvalConfig | None = None
    # Platform mail (P1b-11); without it the API and worker send nothing.
    mail: MailConfig | None = None


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
    # Platform mail (P1b-11), optional; the active [mail] provider's key.
    scaleway_tem_api_key: SecretStr | None = None
    scaleway_tem_project_id: str | None = None
    mailgun_api_key: SecretStr | None = None


@dataclass(frozen=True)
class Settings:
    models: ModelsConfig
    secrets: Secrets
    config_dir: Path
    # The deployed build (``deploy_version``); in the answer cache key.
    deploy_version: str = "unversioned"


def _tree_bytes(root: Path, pattern: str) -> Iterator[bytes]:
    for path in sorted(p for p in root.rglob(pattern) if p.is_file()):
        yield path.relative_to(root).as_posix().encode("utf-8") + b"\x00"
        yield path.read_bytes() + b"\x00"


def deploy_version(env: Mapping[str, str], config_dir: Path) -> str:
    """``ASK_SPORE_DEPLOY_VERSION`` (the git commit or image build ID the Compose file
    passes), or, when it is unset, ``files-`` and a hash of every file in the config
    directory and of the API's own code, so a change to either still changes it."""
    value = env.get(DEPLOY_VERSION_ENV, "").strip()
    if value:
        return value
    digest = hashlib.sha256()
    for part in (*_tree_bytes(config_dir, "*"), *_tree_bytes(APP_DIR, "*.py")):
        digest.update(part)
    return "files-" + digest.hexdigest()[:16]


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
        if entry.currency == "USD" and models.pricing.usd_to_eur is None:
            problems.append(f"{where}: currency USD needs [pricing] usd_to_eur")
        if (entry.provider_order or entry.provider_only) and entry.provider != "openrouter":
            problems.append(f"{where}: provider_order and provider_only are for openrouter")
        if entry.provider_only and not entry.provider_order:
            problems.append(f"{where}: provider_only needs a provider_order")
        for slug in entry.provider_order:
            if not _PROVIDER_SLUG.fullmatch(slug):
                problems.append(f"{where}: provider_order '{slug}' is not a provider slug")
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
            for field in ("chat_model", "rewrite_model")
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
    if models.mail is not None:
        mail = models.mail
        if getattr(mail, mail.provider) is None:
            problems.append(
                f"mail.provider is '{mail.provider}' but there is no [mail.{mail.provider}]"
            )
        for name, section in (("scaleway", mail.scaleway), ("mailgun", mail.mailgun)):
            if section is None:
                continue
            # Mail carries recipients' addresses: EU hosts only, never an external host.
            eu_outbound[f"mail.{name}.base_url"] = section.base_url
            if urlsplit(section.base_url).scheme != "https":
                problems.append(f"mail.{name}.base_url must use https")
    _check_hosts(problems, eu_outbound, eu, "eu_hosts")
    if "latest" in models.ragflow.embedding_model.lower():
        problems.append("ragflow.embedding_model must name a fixed model, not a '-latest' alias")
    problems += _check_ragflow_ui(models.ragflow)
    problems += _check_eval(models)
    problems += _check_eval_service(models.auth)
    return problems + _check_catalogue(models)


def _check_eval_service(auth: AuthConfig) -> list[str]:
    """The service credential is an ``oidc``-mode path with an Ed25519 public key."""
    service = auth.eval_service
    if service is None:
        return []
    if auth.mode != "oidc":
        return ["auth.eval_service needs [auth] mode = 'oidc'"]
    from app.auth.eval_service import load_public_key

    try:
        load_public_key(service.public_key)
    except Exception:  # any unreadable or non-Ed25519 key
        return ["auth.eval_service.public_key must be an Ed25519 public key (PEM)"]
    return []


def _check_eval(models: ModelsConfig) -> list[str]:
    """The judge must be a fixed model its (EU) provider pins (P1b-15 c)."""
    judge = models.eval
    if judge is None:
        return []
    model = judge.judge_model
    if "latest" in model.lower() or not _FIXED_MODEL.fullmatch(model):
        return [f"eval.judge_model '{model}' must be a fixed model name, not an alias"]
    if judge.judge_provider == "scaleway":
        if models.scaleway is None:
            return ["eval.judge_provider is 'scaleway' but there is no [scaleway] section"]
        pinned = {
            models.scaleway.chat_model,
            models.scaleway.rewrite_model,
            *models.scaleway.models,
        }
    else:
        pinned = {models.mistral.chat_model, models.mistral.rewrite_model}
    if model not in pinned:
        return [f"eval.judge_model '{model}' is not pinned in [{judge.judge_provider}]"]
    return []


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _check_ragflow_ui(ragflow: RagflowConfig) -> list[str]:
    """P1b-05: the console's RAGFlow link points at the loopback admin UI, never a public
    or Compose-network address (RAGFlow is internal, CLAUDE.md)."""
    problems: list[str] = []
    if ragflow.admin_ui_url is not None:
        parts = urlsplit(ragflow.admin_ui_url)
        if parts.scheme != "http" or (parts.hostname or "") not in LOOPBACK_HOSTS:
            problems.append("ragflow.admin_ui_url must be an http://127.0.0.1 (loopback) URL")
        elif parts.path not in ("", "/") or parts.query or parts.fragment:
            problems.append("ragflow.admin_ui_url must be a bare origin (http://127.0.0.1:8080)")
    for name, path in (
        ("admin_ui_dataset_path", ragflow.admin_ui_dataset_path),
        ("admin_ui_document_path", ragflow.admin_ui_document_path),
    ):
        try:
            filled = path.format(dataset_id="d", document_id="x")
        except (KeyError, IndexError, ValueError):
            filled = ""
        if not filled.startswith("/") or "//" in filled or "{dataset_id}" not in path:
            problems.append(f"ragflow.{name} must be a path with {{dataset_id}}")
    return problems


def _check_prompts(prompts: PromptsConfig, directory: Path) -> list[str]:
    problems: list[str] = []
    for name, version in prompts.model_dump().items():
        path = directory / "prompts" / name / f"{version}.md"
        if not path.is_file():
            problems.append(f"prompts.{name} = '{version}' but {path} does not exist")
        elif not (text := path.read_text(encoding="utf-8")).strip():
            problems.append(f"prompts.{name}: {path} is empty")
        else:
            # P1a-06: the workspace-instructions slot, when present, must be well formed.
            problems += [f"prompts.{name}: {path.name} {p}" for p in check_slot(text)]
    return problems


def _check_consent(consent: ConsentConfig, directory: Path) -> list[str]:
    return [f"consent.version: {problem}" for problem in check_notice(directory, consent.version)]


def _check_mail_templates(mail: MailConfig | None, directory: Path) -> list[str]:
    if mail is None:
        return []
    versions = mail.templates.model_dump()
    return [
        f"mail.templates.{name}: {problem}"
        for name in TEMPLATE_NAMES
        for problem in check_template(directory, name, versions[name])
    ]


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
        problems += _check_mail_templates(models.mail, directory)
        problems += _check_consent(models.consent, directory)

    provider = models.llm.provider if models is not None else None
    auth_mode = models.auth.mode if models is not None else None
    required = [
        *REQUIRED_SECRETS,
        *([PROVIDER_SECRETS[provider]] if provider else []),
        *(AUTH_SECRETS[auth_mode] if auth_mode else ()),
    ]
    if models is not None and models.llm.eu_failover:
        backup = "mistral" if models.llm.provider == "scaleway" else "scaleway"
        if backup == "scaleway" and models.scaleway is None:
            problems.append("llm.eu_failover needs a [scaleway] section")
        required.append(PROVIDER_SECRETS[backup])
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        problems.append("missing required secrets in the environment: " + ", ".join(missing))
    token = env.get("PHASE0_BEARER_TOKEN", "").strip()
    if token and len(token) < MIN_BEARER_TOKEN_LENGTH:
        problems.append(
            f"PHASE0_BEARER_TOKEN must be at least {MIN_BEARER_TOKEN_LENGTH} characters"
        )

    # P1c-03: no deployment users sign in to runs on a password the repository publishes.
    if auth_mode == "oidc":
        published = published_credentials(env)
        if published:
            problems.append(
                "credentials equal to a value published in the repository (.env.example, "
                "Compose defaults, CI): " + ", ".join(published) + "; rotate them "
                "(infra/README.md, Credentials rotation)"
            )

    version = env.get(DEPLOY_VERSION_ENV, "").strip()
    if version and not _DEPLOY_VERSION.fullmatch(version):
        problems.append(
            f"{DEPLOY_VERSION_ENV} must be a commit or build ID (letters, digits, . _ : + -)"
        )

    project = env.get(SCALEWAY_PROJECT_ENV, "").strip() or None
    if project is not None and not _UUID.fullmatch(project):
        problems.append(f"{SCALEWAY_PROJECT_ENV} must be a project UUID")
    mail_project = env.get(SCALEWAY_TEM_PROJECT_ENV, "").strip() or None
    if mail_project is not None and not _UUID.fullmatch(mail_project):
        problems.append(f"{SCALEWAY_TEM_PROJECT_ENV} must be a project UUID")

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
        scaleway_tem_api_key=optional(SCALEWAY_TEM_KEY_ENV),
        scaleway_tem_project_id=mail_project or project,
        mailgun_api_key=optional(MAILGUN_KEY_ENV),
    )
    return Settings(
        models=models,
        secrets=secrets,
        config_dir=directory,
        deploy_version=deploy_version(env, directory),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, loaded once from the real environment."""
    return load_settings()
