"""Builders for per-item records used across the harness tests."""

from __future__ import annotations

from eval.records import (
    CitationRecord,
    ItemResult,
    JudgedStatement,
    JudgeRecord,
    Outcome,
    PipelineRecord,
    RetrievalRecord,
    Verdict,
)

A = "https://example.org/a"
B = "https://example.org/b"


def result(
    item_id: str,
    item_type: str = "factual",
    *,
    outcome: Outcome = "answered",
    hit5: bool | None = True,
    hit10: bool | None = True,
    precision: float | None = 1.0,
    verdicts: tuple[Verdict, ...] = ("supported",),
    would_abstain: bool = False,
    cached: bool = False,
) -> ItemResult:
    ooc = item_type == "out_of_corpus"
    judged = outcome in ("answered", "unsupported")
    return ItemResult(
        id=item_id,
        type=item_type,
        labels=[],
        expected_source_ids=[] if ooc else [A],
        retrieval=RetrievalRecord(
            hit_at_5=None if ooc else hit5,
            hit_at_10=None if ooc else hit10,
            would_abstain=would_abstain,
        ),
        pipeline=PipelineRecord(
            outcome=outcome,
            error_code="llm_5xx" if outcome == "error" else None,
            answer="An answer.",
            citations=[CitationRecord(1, "c1", "s1", A, "Title", None, None if ooc else True)]
            if outcome == "answered"
            else [],
            citation_precision=None if ooc or outcome != "answered" else precision,
            cached=cached,
            tokens_in=10,
            tokens_out=5,
        ),
        judge=JudgeRecord(
            statements=[JudgedStatement(f"s{n}", (1,), v) for n, v in enumerate(verdicts)],
            faithfulness=(
                None
                if not [v for v in verdicts if v != "no_claim"]
                else sum(v == "supported" for v in verdicts)
                / len([v for v in verdicts if v != "no_claim"])
            ),
        )
        if judged
        else None,
    )
