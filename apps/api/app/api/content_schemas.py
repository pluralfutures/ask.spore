"""Request and response bodies of the content console, /api/v1/content (P1b-05).

Metadata only: no document text beyond a source's title and register metadata, and no
request body carries a dataset or document ID (the RAGFlow links are built server-side
from the register). A proposal with a file is a multipart form (``app.api.content``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas import _In

MAX_NOTE_CHARS = 2000
MAX_PATTERNS = 50


class ContentMeOut(BaseModel):
    roles: list[str]
    # The loopback RAGFlow UI for chunk spot-checks (over an SSH tunnel), when configured.
    ragflow_ui_url: str | None


class ContentSourceOut(BaseModel):
    """A register row in the list."""

    id: UUID
    type: str
    title: str
    publisher: str
    published_on: date | None
    canonical_url: str | None
    licence_basis: str
    tags: list[str]
    status: str
    downloadable: bool
    site_id: UUID | None
    takedown_due_on: date | None
    possible_replacement: bool  # proposed at the canonical link of an ingested source
    created_at: datetime
    updated_at: datetime


class SourceRef(BaseModel):
    id: UUID
    title: str
    publisher: str
    status: str


class DocumentLink(BaseModel):
    """One RAGFlow document of a source, for chunk spot-checks in the private UI."""

    tag: str
    dataset_id: str
    document_id: str
    ragflow_url: str | None  # loopback admin UI, operator-only over an SSH tunnel


class HistoryEntry(BaseModel):
    event: str
    at: datetime
    actor: str | None  # the internal user's email; None for the worker or the shell
    before: str | None
    after: str | None
    method: str | None


class JobOut(BaseModel):
    id: UUID
    type: str
    status: str
    error_code: str | None
    attempts: int
    created_at: datetime
    finished_at: datetime | None


class TakedownOut(BaseModel):
    source_id: UUID
    title: str
    status: str
    reference: str
    requested_on: date
    due_on: date
    working_days_left: int  # negative when overdue
    licence_grounds: bool


class ContentSourceDetail(ContentSourceOut):
    review_note: str | None
    review_date: date | None
    proposed_by: str | None
    approved_by: str | None
    approved_at: datetime | None
    withdrawn_at: datetime | None
    withdrawal_reason: str | None
    chunk_count: int | None
    error: str | None  # the ingestion error RAGFlow reported, for a failed source
    licence_file: bool
    stored: bool
    fetched_at: datetime | None
    supersedes: SourceRef | None
    possible_replacements: list[SourceRef]
    takedown: TakedownOut | None
    documents: list[DocumentLink]
    history: list[HistoryEntry]
    jobs: list[JobOut]


class ProposeOut(BaseModel):
    """``proposed``: a new row. Otherwise the file is already in the register:
    ``pending`` (waits for a reviewer), ``duplicate`` (ingested in every tag),
    ``retag`` (ingested; adding tags needs a reviewer, from the CLI for now) or
    ``taken_down`` (withdrawn after a takedown request; not proposed again)."""

    source_id: UUID
    outcome: Literal["proposed", "pending", "duplicate", "retag", "taken_down"]
    status: str
    possible_replacements: list[SourceRef]
    # Owner decision 3: same canonical link and title as this ingested source, which the
    # proposal replaces once approved and ingested (no choice needed).
    replaces: SourceRef | None = None


class ApproveIn(_In):
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    # Owner decision 4: for a possible replacement, the source it replaces, or keep both.
    replaces: UUID | None = None
    keep_both: bool = False


class NoteIn(_In):
    note: str = Field(min_length=1, max_length=MAX_NOTE_CHARS)


class WithdrawIn(_In):
    reason: str = Field(min_length=1, max_length=MAX_NOTE_CHARS)


class TakedownIn(_In):
    reference: str = Field(min_length=1, max_length=128)
    requested_on: date
    licence_breach: bool = False
    licence_grounds: bool = False


class JobQueuedOut(BaseModel):
    job_id: UUID


class SiteWithdrawnOut(BaseModel):
    """P1c-14: the per-page ``withdraw_source`` jobs a site withdrawal queued."""

    job_ids: list[UUID]


class SiteReinstatedOut(BaseModel):
    """P2A-12 (a): pages released for the next crawl, and pages kept blocked for a
    takedown. The site is ``proposed`` and needs a fresh approval."""

    released: int
    kept_blocked: int


class SiteOut(BaseModel):
    id: UUID
    name: str
    start_url: str
    host: str
    publisher: str
    licence_basis: str
    tags: list[str]
    status: str
    schedule: str
    max_pages: int
    allow_decision: str
    allow_checked_at: datetime | None
    last_crawl_at: datetime | None
    last_crawl_status: str | None
    next_crawl_at: datetime | None
    page_count: int
    blocked_count: int


class SitePageOut(BaseModel):
    url: str
    state: str
    reason: str | None
    special_category: str | None
    source_id: UUID | None
    published_on: date | None
    fetched_at: datetime | None


class SiteDetail(SiteOut):
    allow_patterns: list[str]
    deny_patterns: list[str]
    special_category_allow: list[str]
    review_note: str | None
    proposed_by: str | None
    approved_by: str | None
    approved_at: datetime | None
    withdrawn_at: datetime | None  # P1c-14: the whole site was withdrawn
    withdrawal_reason: str | None
    pages: list[SitePageOut]
    jobs: list[JobOut]


Schedule = Literal["none", "weekly", "monthly"]


class SiteCreateIn(_In):
    start_url: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=300)
    licence_basis: str = Field(min_length=1, max_length=300)
    tags: list[str] = Field(min_length=1, max_length=20)
    allow_patterns: list[str] = Field(default_factory=list, max_length=MAX_PATTERNS)
    deny_patterns: list[str] = Field(default_factory=list, max_length=MAX_PATTERNS)
    schedule: Schedule = "none"
    max_pages: int = Field(default=50, ge=1, le=5000)


class SiteSettingsIn(_In):
    allow_patterns: list[str] = Field(default_factory=list, max_length=MAX_PATTERNS)
    deny_patterns: list[str] = Field(default_factory=list, max_length=MAX_PATTERNS)
    schedule: Schedule
    max_pages: int = Field(ge=1, le=5000)


class SiteApproveIn(_In):
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)


class PatternsIn(_In):
    patterns: list[str] = Field(max_length=MAX_PATTERNS)


class TagOut(BaseModel):
    """A tag of ``config/tags.toml`` and its RAGFlow dataset (the ``datasets`` table)."""

    tag: str
    chunk_method: str
    chunk_method_by_type: dict[str, str]
    dataset_id: str | None
    ragflow_url: str | None
    sources: int  # ingested sources in the tag


class TagSyncOut(BaseModel):
    tag: str
    status: str
    dataset_id: str | None
