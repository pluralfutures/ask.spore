"""P0-14 helpers: citation marker filtering and context chunk selection."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.chat.citations import MarkerFilter, filter_markers, strip_markers
from app.chat.context import select_context
from app.chat.package import Provenance
from app.chat.tokens import count_tokens, truncate_tokens
from app.retrieval.types import RetrievedChunk


@pytest.mark.parametrize(
    ("text", "count", "expected", "cited"),
    [
        ("Grew [1].", 3, "Grew [1].", [1]),
        ("Grew [4].", 3, "Grew .", []),
        ("Grew [0] and [3].", 3, "Grew  and [3].", [3]),
        ("Both [1, 3] and [2,9].", 3, "Both [1][3] and [2].", [1, 3, 2]),
        ("Again [2][2] then [1].", 3, "Again [2][2] then [1].", [2, 1]),
        ("Text [sic] and [2025 figures] and [].", 3, "Text [sic] and [2025 figures] and [].", []),
        ("Unclosed [2", 3, "Unclosed [2", []),
        ("Nested [[1]]", 3, "Nested [[1]]", [1]),
        ("Nothing cited.", 3, "Nothing cited.", []),
        ("Any [1] with no context", 0, "Any  with no context", []),
    ],
)
def test_filter_markers(text: str, count: int, expected: str, cited: list[int]) -> None:
    assert filter_markers(text, count) == (expected, cited)


def test_marker_filter_handles_markers_split_across_deltas() -> None:
    markers = MarkerFilter(2)
    deltas = ["Capacity grew ", "[", "1", "]. Also [", "1", "2] and [2", "]", " end ["]
    out = "".join(markers.feed(d) for d in deltas) + markers.flush()
    assert out == "Capacity grew [1]. Also  and [2] end ["
    assert markers.cited == [1, 2]


def test_marker_filter_holds_back_only_while_a_marker_is_possible() -> None:
    markers = MarkerFilter(5)
    assert markers.feed("Rate [") == "Rate "
    assert markers.feed("3") == ""
    assert markers.feed("x") == "[3x"


def test_strip_markers() -> None:
    assert strip_markers("Grew [1][2] and [3, 4] [note].") == "Grew  and  [note]."


def _prov(source: uuid.UUID, kind: str = "pdf") -> Provenance:
    return Provenance(source, kind, "Title", "Publisher", date(2026, 1, 1), "https://example.org")


def _chunk(cid: str, doc: str, text: str, score: float, dataset: str = "ds-a") -> RetrievedChunk:
    return RetrievedChunk(cid, doc, dataset, text, score, None)


def test_select_context_filters_orders_dedupes_and_caps() -> None:
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    provenance = {"d1": _prov(s1), "d1-copy": _prov(s1), "d2": _prov(s2, "html")}
    chunks = [
        _chunk("low", "d2", "below threshold", 0.1),
        _chunk("c2", "d2", "Second source text.", 0.6),
        _chunk("c1", "d1", "First source, best text.", 0.9),
        # The same document linked into a second tag dataset: an exact duplicate.
        _chunk("c1-copy", "d1-copy", "First  source, BEST text.", 0.85, dataset="ds-b"),
        _chunk("c1-part", "d1", "best text", 0.5),  # contained in c1: an overlap
        _chunk("orphan", "unknown-doc", "No register row.", 0.95),
        _chunk("foreign", "d2", "Dataset outside the package.", 0.99, dataset="ds-z"),
        _chunk("blank", "d2", "   ", 0.99),
    ]
    selected = select_context(
        chunks,
        provenance,
        dataset_ids=["ds-a", "ds-b"],
        similarity_threshold=0.2,
        max_tokens=1000,
    )
    assert [c.chunk.chunk_id for c in selected] == ["c1", "c2"]
    assert selected[1].for_prompt().untrusted is True
    assert selected[0].for_prompt().untrusted is False


def test_select_context_token_cap_skips_what_does_not_fit() -> None:
    s = uuid.uuid4()
    provenance = {"d": _prov(s)}
    chunks = [
        _chunk("a", "d", " apple" * 40, 0.9),  # 40 tokens
        _chunk("b", "d", " river" * 80, 0.8),  # 80 tokens
        _chunk("c", "d", " stone" * 50, 0.7),  # 50 tokens
    ]
    assert [count_tokens(c.text) for c in chunks] == [40, 80, 50]
    selected = select_context(
        chunks, provenance, dataset_ids=["ds-a"], similarity_threshold=0, max_tokens=100
    )
    assert [c.chunk.chunk_id for c in selected] == ["a", "c"]


def test_select_context_truncates_a_single_oversized_chunk() -> None:
    provenance = {"d": _prov(uuid.uuid4())}
    chunks = [_chunk("big", "d", " apple" * 500, 0.9)]
    selected = select_context(
        chunks, provenance, dataset_ids=["ds-a"], similarity_threshold=0, max_tokens=100
    )
    assert len(selected) == 1
    assert selected[0].chunk.text == " apple" * 100
    assert count_tokens(selected[0].chunk.text) == 100


def test_token_counts_come_from_the_tokenizer_not_characters() -> None:
    # P1b-15 f: a real tokenizer, not 4 characters per token (which would say 9 here).
    english = "Capacity grew by 12 percent in 2025."
    assert count_tokens(english) == 11
    # Text that is short in characters can be long in tokens, and the reverse.
    assert count_tokens("容量增长了百分之十二。") < len("容量增长了百分之十二。")
    assert count_tokens("") == 0
    # Truncation keeps whole characters.
    assert truncate_tokens("€€€€", 1) == "€"
    assert truncate_tokens(english, 100) == english


def test_prompt_chunk_from_context_carries_no_ids() -> None:
    source = uuid.uuid4()
    selected = select_context(
        [_chunk("chunk-xyz", "doc-xyz", "text", 0.9)],
        {"doc-xyz": _prov(source)},
        dataset_ids=["ds-a"],
        similarity_threshold=0,
        max_tokens=100,
    )
    rendered = repr(selected[0].for_prompt())
    for identifier in ("chunk-xyz", "doc-xyz", "ds-a", str(source)):
        assert identifier not in rendered


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("pdf", 3), ("pptx", 3), ("docx", None), ("html", None), ("markdown", None)],
)
def test_page_or_slide_only_for_paged_source_types(kind: str, expected: int | None) -> None:
    # RAGFlow reports page 1 (here 3, to tell it from a default) for every format (R14).
    chunk = RetrievedChunk("c", "d", "ds-a", "text", 0.9, 3)
    selected = select_context(
        [chunk],
        {"d": _prov(uuid.uuid4(), kind)},
        dataset_ids=["ds-a"],
        similarity_threshold=0,
        max_tokens=100,
    )
    assert selected[0].page_or_slide == expected
    assert selected[0].for_prompt().page_or_slide == expected


def test_select_context_dedupes_a_source_linked_into_two_datasets() -> None:
    # R15: one source under two tags is two RAGFlow documents with different chunk and
    # document IDs; only the provenance join tells they are the same source.
    shared, other = uuid.uuid4(), uuid.uuid4()
    provenance = {"doc-a": _prov(shared), "doc-b": _prov(shared), "doc-c": _prov(other)}
    chunks = [
        _chunk("chunk-a", "doc-a", "Capacity grew 12%.", 0.7, dataset="ds-a"),
        _chunk("chunk-b", "doc-b", "Capacity grew 12%.", 0.8, dataset="ds-b"),
        # Same text from a different source is a separate citation.
        _chunk("chunk-c", "doc-c", "Capacity grew 12%.", 0.6, dataset="ds-a"),
    ]
    selected = select_context(
        chunks,
        provenance,
        dataset_ids=["ds-a", "ds-b"],
        similarity_threshold=0,
        max_tokens=100,
    )
    assert [c.chunk.chunk_id for c in selected] == ["chunk-b", "chunk-c"]
