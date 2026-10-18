"""Metric computations (P0-18). Pure functions over the per-item records.

Every headline metric is in points (0 to 100) and higher is better, so ``compare``
can treat them alike. A metric with no applicable item is ``None``.

- ``hit_at_5`` / ``hit_at_10``: share of factual and synthesis items with at least one
  expected source among the sources of the top 5 / 10 retrieved chunks.
- ``citation_precision``: per item with citations, cited sources that are expected
  divided by cited sources (distinct sources); averaged over those items.
- ``faithfulness``: per judged answer, supported statements divided by statements
  making a claim; averaged over judged answers.
- ``abstention_correctness``: share of out_of_corpus items answered without any
  citation: abstained before the LLM, or the model declined (``unsupported``).
- ``in_corpus_answer_rate``: share of factual and synthesis items that got a cited
  answer; the other side of abstention (a stricter threshold lowers it).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from eval.records import ItemResult, SourceRef

HEADLINE: tuple[str, ...] = (
    "hit_at_5",
    "hit_at_10",
    "citation_precision",
    "faithfulness",
    "abstention_correctness",
    "in_corpus_answer_rate",
)
OUT_OF_CORPUS = "out_of_corpus"


def matches(expected: Sequence[str], ref: SourceRef) -> bool:
    """An expected entry names a source by register UUID or by canonical URL."""
    return any(
        entry == ref.source_id or (ref.canonical_url is not None and entry == ref.canonical_url)
        for entry in expected
    )


def hit_at(ranked: Sequence[SourceRef], expected: Sequence[str], k: int) -> bool:
    """``ranked`` holds the source of each retrieved chunk, best chunk first."""
    return any(matches(expected, ref) for ref in ranked[:k])


def citation_precision(cited: Sequence[SourceRef], expected: Sequence[str]) -> float | None:
    distinct = {(ref.source_id, ref.canonical_url): ref for ref in cited}.values()
    if not distinct or not expected:
        return None
    return sum(matches(expected, ref) for ref in distinct) / len(distinct)


def faithfulness(verdicts: Iterable[str]) -> float | None:
    claims = [v for v in verdicts if v != "no_claim"]
    if not claims:
        return None
    return sum(v == "supported" for v in claims) / len(claims)


def points(values: Iterable[float | bool | None]) -> float | None:
    """Mean in points, one decimal; ``None`` values are not applicable and skipped."""
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return round(100 * sum(present) / len(present), 1)


def aggregate(items: Sequence[ItemResult]) -> dict[str, Any]:
    in_corpus = [i for i in items if i.type != OUT_OF_CORPUS]
    ooc = [i for i in items if i.type == OUT_OF_CORPUS]

    def done(group: list[ItemResult]) -> list[ItemResult]:
        return [i for i in group if i.pipeline.outcome != "error"]

    verdicts = [s.verdict for i in items if i.judge for s in i.judge.statements]
    metrics = {
        "hit_at_5": points(i.retrieval.hit_at_5 for i in in_corpus),
        "hit_at_10": points(i.retrieval.hit_at_10 for i in in_corpus),
        "citation_precision": points(i.pipeline.citation_precision for i in in_corpus),
        "faithfulness": points(i.judge.faithfulness for i in items if i.judge),
        "abstention_correctness": points(
            i.pipeline.outcome in ("abstained", "unsupported") for i in done(ooc)
        ),
        "in_corpus_answer_rate": points(i.pipeline.outcome == "answered" for i in done(in_corpus)),
    }
    diagnostics = {
        "out_of_corpus_abstained_without_llm": points(
            i.pipeline.outcome == "abstained" for i in done(ooc)
        ),
        "out_of_corpus_retrieval_would_abstain": points(
            i.retrieval.would_abstain for i in ooc if i.retrieval.error is None
        ),
        "in_corpus_retrieval_would_abstain": points(
            i.retrieval.would_abstain for i in in_corpus if i.retrieval.error is None
        ),
        "statements_supported": verdicts.count("supported"),
        "statements_unsupported": verdicts.count("unsupported"),
        "statements_no_claim": verdicts.count("no_claim"),
    }
    counts = {
        "items": len(items),
        "factual": sum(i.type == "factual" for i in items),
        "synthesis": sum(i.type == "synthesis" for i in items),
        "out_of_corpus": len(ooc),
        "pipeline_errors": sum(i.pipeline.outcome == "error" for i in items),
        "retrieval_errors": sum(i.retrieval.error is not None for i in items),
        "judge_errors": sum(1 for i in items if i.judge and i.judge.error),
        "cached_answers": sum(i.pipeline.cached for i in items),
        "excerpt_fallbacks": sum(i.judge.excerpt_fallbacks for i in items if i.judge),
        "answered": sum(i.pipeline.outcome == "answered" for i in items),
        "unsupported": sum(i.pipeline.outcome == "unsupported" for i in items),
        "abstained": sum(i.pipeline.outcome == "abstained" for i in items),
        "pipeline_tokens_in": sum(i.pipeline.tokens_in for i in items),
        "pipeline_tokens_out": sum(i.pipeline.tokens_out for i in items),
        "judge_tokens_in": sum(i.judge.tokens_in for i in items if i.judge),
        "judge_tokens_out": sum(i.judge.tokens_out for i in items if i.judge),
    }
    return {"metrics": metrics, "diagnostics": diagnostics, "counts": counts}
