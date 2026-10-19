"""Request and response bodies for /api/v1 (P0-15). The OpenAPI schema is built from these.

No request body carries a tenant, user, dataset or document ID: those come from
authentication and from the server-side package.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUESTION_CHARS = 4000
MAX_COMMENT_CHARS = 2000
MAX_INSTRUCTIONS_CHARS = 2000  # app.tenancy.workspaces.PROMPT_MAX_CHARS
AnswerMode = Literal["corpus_only", "general_knowledge"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class ConversationDetail(ConversationSummary):
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


class LinkRequestOut(BaseModel):
    """Identical for every address (no enumeration)."""

    status: Literal["sent_if_known"]


class LinkCompleteIn(_In):
    token: str = Field(min_length=1, max_length=512)


class MeOut(BaseModel):
    email: str
    display_name: str
    role: Literal["user", "tenant_admin"]
    tenant_display_name: str


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
    answer_modes: list[Literal["corpus_only", "general_knowledge"]] = Field(min_length=1)
    enabled_models: list[str] = Field(min_length=1, max_length=20)
    external_models_enabled: bool
    external_spend_cap_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    sign_in_links_enabled: bool
    # Required when this request switches external models on.
    external_acceptance: AcceptanceIn | None = None


class EntitlementsOut(_Out):
    answer_modes: list[str]
    enabled_models: list[str]
    external_models_enabled: bool
    external_spend_cap_cents: int | None
    sign_in_links_enabled: bool
    external_acceptance_reference: str | None
    external_acceptance_date: date | None
    updated_at: datetime


class TenantOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    verified_domains: list[str]
    status: str
    created_at: datetime
    admins: int
    entitlements: EntitlementsOut


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
