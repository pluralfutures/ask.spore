"""What the harness records per item. Serialised as-is into ``results.json``.

No chunk text is recorded: results are committed to the repository, and chunks are
licensed third-party text. Answers and the judged statements are recorded so a
reviewer can check the metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Outcome = Literal["answered", "unsupported", "abstained", "error"]
Verdict = Literal["supported", "unsupported", "no_claim"]


@dataclass(frozen=True)
class SourceRef:
    """A source register row as the harness sees it: UUID and canonical URL."""

    source_id: str | None
    canonical_url: str | None


@dataclass(frozen=True)
class RankedChunk:
    rank: int  # 1-based, best score first
    chunk_id: str
    score: float
    source_id: str | None  # None when the document has no live register row
    canonical_url: str | None


@dataclass
class RetrievalRecord:
    """The orchestrator's retrieval step for the item's question."""

    chunks: list[RankedChunk] = field(default_factory=list)
    context_count: int = 0  # passages left after threshold, de-duplication and token cap
    would_abstain: bool = False  # nothing left: the orchestrator answers without the LLM
    hit_at_5: bool | None = None  # None for out_of_corpus items or on error
    hit_at_10: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class CitationRecord:
    marker: int
    chunk_id: str
    source_id: str
    canonical_url: str | None
    title: str
    page_or_slide: int | None
    expected: bool | None  # the cited source is one of the item's expected sources


@dataclass
class PipelineRecord:
    """The full pipeline (``POST /conversations/{id}/messages``) for the item's question."""

    outcome: Outcome = "error"
    error_code: str | None = None
    answer: str = ""
    citations: list[CitationRecord] = field(default_factory=list)
    citation_precision: float | None = None  # None without citations or expected sources
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass(frozen=True)
class JudgedStatement:
    text: str
    markers: tuple[int, ...]
    verdict: Verdict


@dataclass
class JudgeRecord:
    statements: list[JudgedStatement] = field(default_factory=list)
    faithfulness: float | None = None  # supported / (supported + unsupported)
    excerpt_fallbacks: int = 0  # passages judged from the 1,200-character citation excerpt
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


@dataclass
class ItemResult:
    id: str
    type: str
    labels: list[str]
    expected_source_ids: list[str]
    retrieval: RetrievalRecord
    pipeline: PipelineRecord
    judge: JudgeRecord | None  # None when the LLM was not called (abstained, error)
