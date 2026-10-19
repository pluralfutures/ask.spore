"""Request and response bodies for /api/v1 (P0-15). The OpenAPI schema is built from these.

No request body carries a tenant, user, dataset or document ID: those come from
authentication and from the server-side package.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
