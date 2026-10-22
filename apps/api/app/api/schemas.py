"""Request and response bodies for /api/v1 (P0-15). The OpenAPI schema is built from these.

No request body carries a tenant, user, dataset or document ID: those come from
authentication and from the server-side package.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

MAX_QUESTION_CHARS = 4000
MAX_COMMENT_CHARS = 2000
MAX_INSTRUCTIONS_CHARS = 2000  # app.tenancy.workspaces.PROMPT_MAX_CHARS
AnswerMode = Literal["corpus_only", "general_knowledge"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# C0 control characters other than tab and newline (findings §12): PostgreSQL refuses
# NUL in text, and none of them belongs in a question, comment, prompt or name.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f]")


def _refuse_control_chars(value: object) -> None:
    if isinstance(value, str):
        if _CONTROL_CHARS.search(value):
            raise ValueError("control characters are not allowed")
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _refuse_control_chars(item)


class _In(BaseModel):
    """Base of every request body: no extra fields, no control characters in any text."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _no_control_chars(cls, value: object) -> object:
        _refuse_control_chars(value)
        return value


class ConversationSummary(_Out):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    workspace_id: UUID
    mode: str
    model: str
    reasoning: bool


class ConversationCreateIn(_In):
    """The start panel's choice (P1a-04); each field defaults from the workspace.

    ``workspace_id`` may be left out when the tenant has one workspace. Dataset and
    document IDs are never accepted: the workspace's datasets are resolved server-side.
    """

    workspace_id: UUID | None = None
    mode: AnswerMode | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)
    reasoning: bool | None = None


class ConversationCreated(_Out):
    id: UUID
    title: str | None
    created_at: datetime
    expires_at: datetime
    workspace_id: UUID
    mode: str
    model: str
    reasoning: bool
    # P1a-10: set when the external spend cap made the conversation fall back from
    # the requested model (``external_spend_cap_reached``), with the text to show.
    notice: str | None = None
    notice_text: str | None = None


class WorkspaceOut(_Out):
    id: UUID
    slug: str
    name: str
    default_mode: str
    default_model: str
    default_reasoning: bool


class WorkspacePromptIn(_In):
    """The workspace's additional instructions; an empty text clears them."""

    text: str = Field(max_length=MAX_INSTRUCTIONS_CHARS)


class WorkspacePromptOut(_Out):
    workspace_id: UUID
    version: int
    text: str
    created_at: datetime


class CitationOut(BaseModel):
    marker: int
    source_id: UUID
    chunk_id: str
    page_or_slide: int | None
    excerpt: str
    publisher: str
    title: str
    published_on: date | None
    canonical_url: str | None
    type: str
    # P1b-03, history only: the source was re-ingested since (these chunks are gone) or
    # withdrawn. A citation in a live answer has neither.
    superseded: bool = False
    withdrawn: bool = False


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    mode: str
    created_at: datetime
    unsupported: bool
    abstained: bool
    citations: list[CitationOut]
    # Badge data (P1a-11), assistant messages: the model that answered and whether
    # reasoning was on.
    model: str | None = None
    reasoning: bool | None = None
    # P1b-17: a backup model answered (``model`` is not the conversation's): "eu" or
    # "external" (served outside the EU).
    failover: Literal["eu", "external"] | None = None


class ConversationDetail(ConversationSummary):
    # Header of the conversation (P1a-12): the workspace's label and the model's
    # catalogue display name (the ID when the catalogue no longer lists it).
    workspace_name: str
    model_display_name: str
    messages: list[MessageOut]


class AskIn(_In):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class FeedbackIn(_In):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_CHARS)


class FeedbackOut(BaseModel):
    message_id: UUID
    rating: Literal["up", "down"]
    comment: str | None


class SourceOut(BaseModel):
    id: UUID
    title: str
    publisher: str
    published_on: date | None
    canonical_url: str | None
    type: str
    withdrawn: bool


class Health(BaseModel):
    status: Literal["ok"]


# Server-Sent Events of POST /conversations/{id}/messages. Each SSE frame is
# "event: <name>\ndata: <json>\n\n"; the JSON shapes are these models, in this order:
# any number of `token`, then one `citations`, then one `done` (or one `error`).


class TokenData(BaseModel):
    text: str


class CitationsData(BaseModel):
    citations: list[CitationOut]


class DoneData(BaseModel):
    message_id: UUID
    unsupported: bool
    abstained: bool
    cached: bool
    tokens_in: int
    tokens_out: int
    # Badge data (P1a-11): the conversation's model and its reasoning switch.
    model: str | None
    reasoning: bool
    # The answer stopped at the output budget and is shown as cut off.
    truncated: bool
    # P1b-17: a backup model answered because the conversation's model was unavailable:
    # "eu" (the other EU provider) or "external" (served outside the EU).
    failover: Literal["eu", "external"] | None = None


class ErrorData(BaseModel):
    error_code: str


class ChatStreamEvents(BaseModel):
    """Documentation-only: the data payload of each SSE event name."""

    token: TokenData
    citations: CitationsData
    done: DoneData
    error: ErrorData


# --- authentication (P1a-02) -----------------------------------------------------------


class AuthModeOut(BaseModel):
    mode: Literal["phase0", "oidc"]


class LinkRequestIn(_In):
    email: str = Field(min_length=3, max_length=320)


class DiscoverIn(_In):
    email: str = Field(min_length=3, max_length=320)


class DiscoverOut(BaseModel):
    """The sign-in methods an address's domain allows (P1b-06). The same for every
    address of a domain, and the links-only answer for any unknown domain."""

    methods: list[Literal["sso", "sign_in_link"]]
    sso_kind: Literal["entra", "google", "oidc", "saml"] | None


class LinkRequestOut(BaseModel):
    """Identical for every address (no enumeration)."""

    status: Literal["sent_if_known"]


class LinkCompleteIn(_In):
    token: str = Field(min_length=1, max_length=512)


class MfaRequiredOut(BaseModel):
    """The sign-in waits for the tenant admin's second factor (P1b-08): their TOTP code,
    or first enrolling an authenticator app with ``setup_uri`` (``otpauth://``)."""

    status: Literal["mfa_required"]
    stage: Literal["validate", "setup"]
    setup_uri: str | None
    failed: bool  # the last code was not accepted


class MfaCodeIn(_In):
    code: str = Field(pattern=r"^[0-9]{6,8}$")


class MeOut(BaseModel):
    email: str
    display_name: str
    role: Literal["user", "tenant_admin"]
    tenant_display_name: str
    # P1b-08: the session's access token expiry (OIDC mode); renew before it.
    session_expires_at: datetime | None = None


class ModelOptionOut(BaseModel):
    """A model the signed-in user may pick for a new conversation (P1a-09).

    ``external``: served outside the EU (compliance addendum, Oct 18-19, 2026); the
    model picker says so. ``reasoning_switch``: reasoning can be turned on.
    """

    id: str
    display_name: str
    external: bool
    reasoning_switch: bool
    default: bool


# --- operator console (P1a-03) ---------------------------------------------------------

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}$"
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class TenantCreateIn(_In):
    slug: str = Field(pattern=SLUG_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    verified_domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("verified_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        domains = sorted({domain.strip().lower() for domain in value})
        bad = [d for d in domains if not _DOMAIN.fullmatch(d)]
        if bad:
            raise ValueError("not an email domain")
        return domains


class AcceptanceIn(_In):
    """The client's signed acceptance of external models: the DPA document and date."""

    reference: str = Field(min_length=1, max_length=128)
    accepted_on: date


class EntitlementsIn(_In):
    # P1b-12 (Phase 1a findings F2): the tenant of the console page the save was made on.
    # It must equal the tenant in the path, or nothing is saved (409 tenant_mismatch).
    tenant_id: UUID
    answer_modes: list[Literal["corpus_only", "general_knowledge"]] = Field(min_length=1)
    enabled_models: list[str] = Field(min_length=1, max_length=20)
    external_models_enabled: bool
    external_spend_cap_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    # Required when this request switches external models on.
    external_acceptance: AcceptanceIn | None = None


class EntitlementsOut(_Out):
    answer_modes: list[str]
    enabled_models: list[str]
    external_models_enabled: bool
    external_spend_cap_cents: int | None
    external_acceptance_reference: str | None
    external_acceptance_date: date | None
    updated_at: datetime


class LoginPolicyIn(_In):
    """The operator's switches (P1b-06). The SSO source has its own routes (P1b-07)."""

    sign_in_links_enabled: bool
    jit_provisioning_enabled: bool
    admin_mfa_required: bool


class LoginPolicyOut(_Out):
    """A tenant's login policy: non-secret fields only (P1b-06, P1b-07)."""

    sign_in_links_enabled: bool
    sso_source_kind: Literal["none", "entra", "google", "oidc", "saml"]
    sso_source_slug: str | None
    sso_source_config: dict[str, str | list[str]]
    jit_provisioning_enabled: bool
    admin_mfa_required: bool
    updated_at: datetime
    # P1b-07: what the client's IT registers at their IdP (redirect URI, or SAML ACS URL
    # and SP entity ID), on our public host.
    sso_endpoints: dict[str, str] = Field(default_factory=dict)


# P1b-07: one SSO source per tenant, by kind. Client secrets are write-only: passed to
# Authentik and never stored, returned or logged by the API.
_CLIENT_ID = r"^[A-Za-z0-9][A-Za-z0-9._@:/-]{0,255}$"
ClientSecret = Annotated[SecretStr, Field(min_length=1, max_length=1024)]


class EntraSourceIn(_In):
    kind: Literal["entra"]
    entra_tenant_id: UUID
    client_id: str = Field(pattern=_CLIENT_ID)
    # Required when the source is created or its kind changes; omitted keeps it.
    client_secret: ClientSecret | None = None
    # Entra group object IDs whose members are tenant admins (optional).
    admin_group_ids: list[UUID] = Field(default_factory=list, max_length=20)


class GoogleSourceIn(_In):
    kind: Literal["google"]
    client_id: str = Field(pattern=_CLIENT_ID)
    client_secret: ClientSecret | None = None


class OidcSourceIn(_In):
    kind: Literal["oidc"]
    issuer: str = Field(min_length=9, max_length=512)
    client_id: str = Field(pattern=_CLIENT_ID)
    client_secret: ClientSecret | None = None


class SamlSourceIn(_In):
    kind: Literal["saml"]
    metadata_xml: str = Field(min_length=1, max_length=262_144)

    @field_validator("metadata_xml", mode="before")
    @classmethod
    def _line_endings(cls, value: object) -> object:
        # Metadata files often end lines with CRLF; carriage returns are the only control
        # characters let through, as newlines.
        return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


SsoSourceIn = Annotated[
    EntraSourceIn | GoogleSourceIn | OidcSourceIn | SamlSourceIn, Field(discriminator="kind")
]


class SsoStartOut(BaseModel):
    """Where the browser goes next: the IdP's sign-in page (P1b-07)."""

    redirect_url: str


class TenantOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    verified_domains: list[str]
    status: str
    created_at: datetime
    admins: int
    entitlements: EntitlementsOut
    login_policy: LoginPolicyOut


class AdminInviteIn(_In):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=128)


class AdminInvitedOut(BaseModel):
    user_id: UUID
    status: Literal["invited"]


class NoticeOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_slug: str
    kind: str
    created_at: datetime


class OperatorOptionsOut(BaseModel):
    answer_modes: list[str]
    models: list[str]
    tags: list[str]  # config/tags.toml, assignable to workspaces (P1a-04)


class OperatorTagOut(BaseModel):
    """A tag a tenant's workspaces may use (P1b-12): its own, or shared by all tenants."""

    tag: str
    shared: bool


class ModelSpendOut(BaseModel):
    """One model's month-to-date usage, from ``usage_ledger`` (P1b-12)."""

    model: str
    display_name: str
    external: bool
    tokens_in: int
    tokens_out: int
    cost_cents: Decimal  # euro cents, as the ledger holds them


class SpendThresholdOut(BaseModel):
    percent: int  # 80 or 100
    cents: Decimal  # the threshold in euro cents of the tenant's cap
    reached: bool
    notified_at: datetime | None  # the operator notice for this month, if written


class TenantSpendOut(BaseModel):
    """A tenant's month-to-date usage by model and its external spend against the cap."""

    tenant_id: UUID
    month: str  # YYYY-MM, UTC
    models: list[ModelSpendOut]
    external_spent_cents: Decimal
    external_models_enabled: bool
    external_spend_cap_cents: int | None
    thresholds: list[SpendThresholdOut]


class AggregateModelOut(ModelSpendOut):
    provider: str
    tenants: int  # how many tenants used the model this month


class ProviderTotalOut(BaseModel):
    provider: str
    tokens_in: int
    tokens_out: int
    cost_cents: Decimal


class AggregatesOut(BaseModel):
    """Cross-tenant totals for the month (P1b-12): no tenant is named, no text exists."""

    month: str
    tenants: int
    tenants_with_usage: int
    models: list[AggregateModelOut]
    providers: list[ProviderTotalOut]


TAG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
TagList = list[Annotated[str, Field(pattern=TAG_PATTERN, max_length=64)]]


class WorkspaceCreateIn(_In):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    tag_ids: TagList = Field(default_factory=list, max_length=64)
    default_mode: AnswerMode = "corpus_only"
    default_model: str = Field(min_length=1, max_length=128)
    default_reasoning: bool = False


class WorkspaceTagsIn(_In):
    tag_ids: TagList = Field(max_length=64)


class OperatorWorkspaceOut(WorkspaceOut):
    tenant_id: UUID
    tag_ids: list[str]
    created_at: datetime


class OperatorMeOut(BaseModel):
    email: str
    display_name: str


# --- tenant admin pages (P1a-13) -------------------------------------------------------

UserRole = Literal["user", "tenant_admin"]


class AdminUserOut(_Out):
    id: UUID
    email: str
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    last_login_method: str | None
    created_at: datetime


class UserInviteIn(_In):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=128)
    role: UserRole = "user"


class UserChangeIn(_In):
    """Change a user's role, or deactivate and reactivate them. Users are never deleted."""

    role: UserRole | None = None
    status: Literal["active", "deactivated"] | None = None


class WorkspaceDefaultsIn(_In):
    """A workspace's defaults, among the tenant's enabled modes and models."""

    default_mode: AnswerMode
    default_model: str = Field(min_length=1, max_length=128)
    default_reasoning: bool


class RetentionIn(_In):
    # CLAUDE.md: 30 days maximum; a tenant admin may only shorten it.
    retention_days: int = Field(ge=1, le=30)


class TenantSettingsOut(BaseModel):
    retention_days: int
    max_retention_days: int
    answer_modes: list[str]  # what the operator enabled; workspace defaults pick among them


# --- workspace file list and downloads (P1a-14) ----------------------------------------


class WorkspaceFileOut(BaseModel):
    """A PDF, DOCX or PPTX file of the workspace, from the source register.

    ``id`` is our register's UUID; no RAGFlow dataset or document ID is ever returned.
    ``downloadable``: a download action is offered; otherwise show ``canonical_url``.
    """

    id: UUID
    type: str
    title: str
    publisher: str
    published_on: date | None
    canonical_url: str | None
    ingested_on: date
    downloadable: bool


class WorkspaceSiteOut(BaseModel):
    """A crawled site of the workspace, once, with its number of pages."""

    site: str
    publisher: str
    page_count: int
    last_ingested_on: date


class WorkspaceFilesOut(BaseModel):
    files: list[WorkspaceFileOut]
    sites: list[WorkspaceSiteOut]


class DownloadLinkOut(BaseModel):
    """A single-use link to the file, valid until ``expires_at`` (60 seconds)."""

    url: str
    expires_at: datetime


class OperatorSourceOut(BaseModel):
    """A source register row for the operator's download switch (P1a-14)."""

    id: UUID
    type: str
    title: str
    publisher: str
    tags: list[str]
    status: str
    licence_basis: str
    downloadable: bool
    stored: bool  # our own copy exists, so a download can be served


class SourceDownloadableIn(_In):
    downloadable: bool
