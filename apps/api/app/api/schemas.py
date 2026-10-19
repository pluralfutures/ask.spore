"""Request and response bodies for /api/v1 (P0-15). The OpenAPI schema is built from these.

No request body carries a tenant, user, dataset or document ID: those come from
authentication and from the server-side package.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUESTION_CHARS = 4000
MAX_COMMENT_CHARS = 2000


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


class ConversationCreated(_Out):
    id: UUID
    title: str | None
    created_at: datetime
    expires_at: datetime


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


class OperatorMeOut(BaseModel):
    email: str
    display_name: str
