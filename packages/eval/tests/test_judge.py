"""P0-18: sentence splitting, judge requests and verdict parsing, and the mock judge."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from app.core.config import MistralConfig
from app.llm.mistral import MistralClient, judge_messages
from pydantic import SecretStr

from eval import mock
from eval.judge import (
    AnswerSentence,
    Judge,
    JudgeReplyError,
    build_request,
    parse_verdicts,
    split_sentences,
)
from eval.pipeline import Citation

CONFIG = MistralConfig(
    base_url="https://api.mistral.ai",
    chat_model="mistral-large-2512",
    rewrite_model="mistral-small-2603",
    timeout_seconds=5,
)


def citation(marker: int, chunk_id: str, source_type: str = "pdf", excerpt: str = "") -> Citation:
    return Citation(
        marker=marker,
        chunk_id=chunk_id,
        source_id=str(uuid.uuid4()),
        canonical_url="https://example.org/a",
        publisher="Synthetic Institute",
        title="Synthetic Outlook",
        published_on="2026-03-02",
        page_or_slide=2,
        type=source_type,
        excerpt=excerpt,
    )


def test_markers_after_the_full_stop_stay_with_their_sentence() -> None:
    answer = "Capacity reached 4.2 GW. [1] Costs fell to 61 EUR/MWh [2][3]. Nothing else [9]."
    assert split_sentences(answer) == [
        AnswerSentence("Capacity reached 4.2 GW.", (1,)),
        AnswerSentence("Costs fell to 61 EUR/MWh.", (2, 3)),
        AnswerSentence("Nothing else.", (9,)),
    ]


def test_markdown_lists_headings_and_tables_are_split_into_statements() -> None:
    answer = (
        "## Summary\n"
        "- Peak demand fell 6 percent [1].\n"
        "1. EV charging moved off-peak [2]\n"
        "| Zone | GW |\n| --- | --- |\n| Grey Shoal | 3.4 |\n"
        "[3]\n"
    )
    sentences = split_sentences(answer)
    assert [s.text for s in sentences] == [
        "Summary",
        "Peak demand fell 6 percent.",
        "EV charging moved off-peak",
        "| Zone | GW |",
        "| Grey Shoal | 3.4 |",
    ]
    assert sentences[1].markers == (1,)
    assert sentences[-1].markers == (3,)  # a marker on its own line joins the previous one


def test_request_numbers_cited_chunks_afresh_and_prefers_full_chunk_text() -> None:
    citations = [citation(3, "c3", excerpt="short"), citation(5, "c5", "markdown", "excerpt 5")]
    request = build_request(
        "First claim [5]. Second claim [3][5]. Third [7].",
        citations,
        {"c3": "Full text of chunk three."},
    )
    assert [s.cites for s in request.statements] == [(1,), (2, 1), ()]
    assert [p.text for p in request.passages] == ["excerpt 5", "Full text of chunk three."]
    assert [p.untrusted for p in request.passages] == [True, False]
    assert request.excerpt_fallbacks == 1


def test_judge_request_carries_no_identifiers() -> None:
    citations = [citation(1, "chunk-5d4c3b2a1f0e")]
    request = build_request("Claim [1].", citations, {"chunk-5d4c3b2a1f0e": "Chunk text."})
    wire = json.dumps(judge_messages("Judge.", request.passages, request.statements))
    assert "chunk-5d4c3b2a1f0e" not in wire
    assert citations[0].source_id not in wire
    assert "example.org" not in wire  # canonical URLs are not provenance the prompt carries


def test_parse_verdicts() -> None:
    raw = '{"verdicts": [{"n": 2, "verdict": "no_claim"}, {"n": 1, "verdict": "supported"}]}'
    assert parse_verdicts(raw, 2) == ["supported", "no_claim"]
    for bad in ("not json", '{"verdicts": [{"n": 1, "verdict": "maybe"}]}', "{}", "[]"):
        with pytest.raises(JudgeReplyError):
            parse_verdicts(bad, 1)
    with pytest.raises(JudgeReplyError, match="statement 2"):
        parse_verdicts('{"verdicts": [{"n": 1, "verdict": "supported"}]}', 2)


def client(handler: httpx.MockTransport) -> MistralClient:
    http = httpx.AsyncClient(transport=handler)
    return MistralClient(CONFIG, SecretStr("k"), "Rewrite.", http_client=http)


async def test_judge_with_the_mock_transport_end_to_end() -> None:
    judge = Judge(client(mock.transport()), "Judge prompt.")
    citations = [citation(1, "c1"), citation(2, "c2")]
    texts = {
        "c1": "Installed capacity reached 4.2 GW at the end of 2025.",
        "c2": "Costs fell to 61 EUR/MWh.",
    }
    record = await judge.judge(
        "Installed capacity reached 4.2 GW at the end of 2025. [1] "
        "Costs rose sharply to 99 EUR/MWh in 2030 [2]. "
        "An unsupported aside. So it is.",
        citations,
        texts,
    )
    assert record.error is None
    assert [s.verdict for s in record.statements] == [
        "supported",
        "unsupported",
        "unsupported",
        "no_claim",
    ]
    assert record.faithfulness == pytest.approx(1 / 3)


async def test_judge_errors_are_recorded_not_raised() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock.handler(request).json() | {"choices": []})

    record = await Judge(client(httpx.MockTransport(broken)), "J.").judge(
        "Claim [1].", [citation(1, "c1")], {}
    )
    assert record.error == "judge_unparseable"
    assert record.faithfulness is None

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "down"})

    record = await Judge(client(httpx.MockTransport(down)), "J.").judge(
        "Claim [1].", [citation(1, "c1")], {}
    )
    assert record.error == "llm_5xx"


async def test_an_answer_without_sentences_is_not_sent_to_the_judge() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    record = await Judge(client(httpx.MockTransport(fail)), "J.").judge("  \n", [], {})
    assert record.statements == [] and record.faithfulness is None and record.error is None


async def test_judge_calls_the_pinned_judge_model() -> None:
    # P1b-15 c: [eval] judge_model reaches the wire, not the client's chat model.
    models: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        models.append(json.loads(request.content)["model"])
        return mock.handler(request)

    judge = Judge(client(httpx.MockTransport(record)), "J.", model="mistral-small-2603")
    await judge.judge("Capacity reached 4.2 GW. [1]", [citation(1, "c1")], {"c1": "4.2 GW."})
    assert models == ["mistral-small-2603"]
