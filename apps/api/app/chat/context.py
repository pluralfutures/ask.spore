"""Chunk selection: provenance join, de-duplication and the context token cap."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.chat.package import Provenance
from app.llm.mistral import PromptChunk
from app.retrieval.types import RetrievedChunk

CHARS_PER_TOKEN = 4  # estimate; no tokenizer dependency in Phase 0
# RAGFlow gives DOCX, HTML and Markdown chunks a pseudo-position on page 1, so a page
# or slide number is real only for these source types (findings R14).
PAGED_SOURCE_TYPES = frozenset({"pdf", "pptx"})
_SPACE = re.compile(r"\s+")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _normalise(text: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


@dataclass(frozen=True)
class ContextChunk:
    """A retrieved chunk with its provenance. Its number in the prompt is its index + 1."""

    chunk: RetrievedChunk
    provenance: Provenance

    @property
    def page_or_slide(self) -> int | None:
        if self.provenance.type not in PAGED_SOURCE_TYPES:
            return None
        return self.chunk.page_or_slide

    def for_prompt(self) -> PromptChunk:
        # Only provenance and text cross the model boundary; IDs stay here.
        return PromptChunk(
            publisher=self.provenance.publisher,
            title=self.provenance.title,
            published_on=self.provenance.published_on,
            page_or_slide=self.page_or_slide,
            text=self.chunk.text,
            untrusted=self.provenance.untrusted,
        )


def select_context(
    chunks: Iterable[RetrievedChunk],
    provenance: dict[str, Provenance],
    *,
    dataset_ids: Iterable[str],
    similarity_threshold: float,
    max_tokens: int,
) -> list[ContextChunk]:
    """Best-first chunks that pass the threshold, de-duplicated and within ``max_tokens``.

    Dropped: chunks below the threshold; chunks from a dataset outside the package
    (defence in depth: the retriever was only asked for package datasets); chunks
    whose document has no live source register row; and duplicates. A duplicate is a
    chunk of the same source whose normalised text equals, contains or is contained
    in a better-scored selected chunk's text; the better-scored one is kept. The same
    document linked into several tag datasets yields such duplicates.
    """
    allowed = set(dataset_ids)
    candidates = sorted(
        (
            c
            for c in chunks
            if c.score >= similarity_threshold
            and c.dataset_id in allowed
            and c.document_id in provenance
            and c.text.strip()
        ),
        key=lambda c: c.score,
        reverse=True,
    )
    selected: list[tuple[ContextChunk, str]] = []
    used = 0
    for chunk in candidates:
        source = provenance[chunk.document_id]
        norm = _normalise(chunk.text)
        if any(
            kept.provenance.source_id == source.source_id
            and (norm in kept_norm or kept_norm in norm)
            for kept, kept_norm in selected
        ):
            continue
        cost = estimate_tokens(chunk.text)
        if selected and used + cost > max_tokens:
            continue  # a later, shorter chunk may still fit
        selected.append((ContextChunk(chunk, source), norm))
        used += cost
    if selected and used > max_tokens:
        # Only possible when the single best chunk alone exceeds the cap: truncate it.
        first, _ = selected[0]
        text = first.chunk.text[: max_tokens * CHARS_PER_TOKEN]
        trimmed = RetrievedChunk(
            chunk_id=first.chunk.chunk_id,
            document_id=first.chunk.document_id,
            dataset_id=first.chunk.dataset_id,
            text=text,
            score=first.chunk.score,
            page_or_slide=first.chunk.page_or_slide,
        )
        return [ContextChunk(trimmed, first.provenance)]
    return [kept for kept, _ in selected]
