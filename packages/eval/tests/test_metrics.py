"""P0-18: metric computations on fixture records."""

from __future__ import annotations

import pytest

from eval.metrics import HEADLINE, aggregate, citation_precision, faithfulness, hit_at, points
from eval.records import SourceRef
from tests.factories import A, B, result

UUID_A = "3f2b8c1e-7d4a-4c2b-9e1f-0a1b2c3d4e5f"


def ref(source_id: str | None, url: str | None = None) -> SourceRef:
    return SourceRef(source_id, url)


def test_hit_at_k_matches_by_url_or_uuid_within_the_first_k() -> None:
    ranked = [ref("x"), ref("y", B), ref(None), ref("z"), ref("w"), ref(UUID_A, A)]
    assert hit_at(ranked, [A], 5) is False  # A is the 6th chunk
    assert hit_at(ranked, [A], 10) is True
    assert hit_at(ranked, [UUID_A], 10) is True
    assert hit_at(ranked, [B], 5) is True
    assert hit_at([], [A], 10) is False


def test_citation_precision_counts_distinct_cited_sources() -> None:
    cited = [ref("s1", A), ref("s1", A), ref("s2", B), ref("s3", "https://example.org/c")]
    assert citation_precision(cited, [A, B]) == pytest.approx(2 / 3)
    assert citation_precision(cited, ["https://example.org/other"]) == 0.0
    assert citation_precision([], [A]) is None
    assert citation_precision(cited, []) is None  # out_of_corpus: not applicable


def test_faithfulness_ignores_statements_without_a_claim() -> None:
    assert faithfulness(["supported", "unsupported", "no_claim", "supported"]) == pytest.approx(
        2 / 3
    )
    assert faithfulness(["no_claim"]) is None
    assert faithfulness([]) is None


def test_points_skip_not_applicable_values() -> None:
    assert points([True, False, None, True]) == pytest.approx(66.7)
    assert points([0.5, 1.0]) == 75.0
    assert points([None]) is None


def test_aggregate_on_a_fixture_run() -> None:
    items = [
        result("f1", hit5=True, hit10=True, precision=1.0, verdicts=("supported", "supported")),
        result("f2", hit5=False, hit10=True, precision=0.5, verdicts=("supported", "unsupported")),
        result("f3", hit5=False, hit10=False, outcome="unsupported", verdicts=("no_claim",)),
        result("s1", "synthesis", outcome="abstained", hit5=False, hit10=False, would_abstain=True),
        result("o1", "out_of_corpus", outcome="abstained", would_abstain=True),
        result("o2", "out_of_corpus", outcome="unsupported", verdicts=("no_claim",)),
        result("o3", "out_of_corpus", outcome="answered", verdicts=("unsupported",), cached=True),
        result("o4", "out_of_corpus", outcome="error"),
    ]
    summary = aggregate(items)
    m = summary["metrics"]
    assert set(m) == set(HEADLINE)
    assert m["hit_at_5"] == 25.0  # 1 of 4 in-corpus items
    assert m["hit_at_10"] == 50.0
    assert m["citation_precision"] == 75.0  # mean of 1.0 and 0.5; others have no citations
    # f1 1.0, f2 0.5, o3 0.0; f3 and o2 have no claim; abstained and errored are not judged
    assert m["faithfulness"] == 50.0
    assert m["abstention_correctness"] == pytest.approx(66.7)  # o1, o2 of o1-o3; o4 errored
    assert m["in_corpus_answer_rate"] == 50.0  # f1, f2 of 4

    d = summary["diagnostics"]
    assert d["out_of_corpus_abstained_without_llm"] == pytest.approx(33.3)
    assert d["out_of_corpus_retrieval_would_abstain"] == 25.0
    assert d["in_corpus_retrieval_would_abstain"] == 25.0
    assert (d["statements_supported"], d["statements_unsupported"], d["statements_no_claim"]) == (
        3,
        2,
        2,
    )
    c = summary["counts"]
    assert (c["items"], c["factual"], c["synthesis"], c["out_of_corpus"]) == (8, 3, 1, 4)
    assert c["pipeline_errors"] == 1
    assert c["cached_answers"] == 1
    assert (c["answered"], c["unsupported"], c["abstained"]) == (3, 2, 2)


def test_aggregate_without_applicable_items_reports_none() -> None:
    m = aggregate([result("o1", "out_of_corpus", outcome="abstained")])["metrics"]
    assert m["hit_at_5"] is None
    assert m["citation_precision"] is None
    assert m["faithfulness"] is None
    assert m["in_corpus_answer_rate"] is None
    assert m["abstention_correctness"] == 100.0
