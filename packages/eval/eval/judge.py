"""Faithfulness judge (P0-18).

The answer is split into sentences; each keeps the ``[n]`` markers it carries. Each
sentence is judged against the passages it cites, numbered afresh for the judge.
The request goes through ``app.llm.mistral.MistralClient.judge`` (EU endpoint, pinned
model, prompt ``config/prompts/judge/<version>.md``), so it carries only the judge
prompt, the cited passages with provenance and the statements.

Passage text is the full chunk text from the retrieval step when the cited chunk is
there (same query, same parameters as the pipeline), otherwise the citation's
excerpt, which the API truncates; such fallbacks are counted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import cast

from app.chat.package import UNTRUSTED_SOURCE_TYPES
from app.llm.mistral import LLMError, MistralClient, PromptChunk, Statement

from eval.metrics import faithfulness
from eval.pipeline import Citation
from eval.records import JudgedStatement, JudgeRecord, Verdict

VERDICTS: tuple[Verdict, ...] = ("supported", "unsupported", "no_claim")

_MARKER = re.compile(r"\[(\d+)\]")
# "Text. [1][2]" -> "Text [1][2]." so the markers stay with their sentence.
_MARKERS_AFTER_STOP = re.compile(r"([.!?])((?:\s*\[\d+\])+)")
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]|\d+[.)]|#{1,6}|>)\s+")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.!?,;:])")
_WORD = re.compile(r"\w")


@dataclass(frozen=True)
class AnswerSentence:
    text: str  # without markers
    markers: tuple[int, ...]


def split_sentences(answer: str) -> list[AnswerSentence]:
    sentences: list[AnswerSentence] = []
    for raw_line in answer.splitlines():
        if _TABLE_RULE.match(raw_line):
            continue
        line = _LIST_PREFIX.sub("", raw_line)
        line = _MARKERS_AFTER_STOP.sub(lambda m: f"{m.group(2)}{m.group(1)}", line)
        for piece in _BOUNDARY.split(line):
            markers = tuple(dict.fromkeys(int(n) for n in _MARKER.findall(piece)))
            text = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(_MARKER.sub(" ", piece).split()))
            if not _WORD.search(text):
                if markers and sentences:  # stray markers belong to the previous sentence
                    last = sentences[-1]
                    merged = tuple(dict.fromkeys(last.markers + markers))
                    sentences[-1] = AnswerSentence(last.text, merged)
                continue
            sentences.append(AnswerSentence(text, markers))
    return sentences


def _published(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class JudgeRequest:
    sentences: list[AnswerSentence]
    passages: list[PromptChunk]
    statements: list[Statement]
    excerpt_fallbacks: int


def build_request(
    answer: str, citations: Sequence[Citation], chunk_texts: Mapping[str, str]
) -> JudgeRequest:
    by_marker = {c.marker: c for c in citations}
    numbers: dict[str, int] = {}
    passages: list[PromptChunk] = []
    fallbacks = 0
    sentences = split_sentences(answer)
    statements: list[Statement] = []
    for sentence in sentences:
        cites: list[int] = []
        for marker in sentence.markers:
            citation = by_marker.get(marker)
            if citation is None:
                continue  # the orchestrator already dropped dangling markers
            if citation.chunk_id not in numbers:
                text = chunk_texts.get(citation.chunk_id)
                if text is None:
                    text, fallbacks = citation.excerpt, fallbacks + 1
                numbers[citation.chunk_id] = len(passages) + 1
                passages.append(
                    PromptChunk(
                        publisher=citation.publisher,
                        title=citation.title,
                        published_on=_published(citation.published_on),
                        page_or_slide=citation.page_or_slide,
                        text=text,
                        untrusted=citation.type in UNTRUSTED_SOURCE_TYPES,
                    )
                )
            cites.append(numbers[citation.chunk_id])
        statements.append(Statement(text=sentence.text, cites=tuple(dict.fromkeys(cites))))
    return JudgeRequest(sentences, passages, statements, fallbacks)


class JudgeReplyError(ValueError):
    """The judge's reply is not the JSON the prompt asks for."""


def parse_verdicts(raw: str, count: int) -> list[Verdict]:
    try:
        data = json.loads(raw)
        entries = data["verdicts"]
        found = {int(e["n"]): e["verdict"] for e in entries}
    except (ValueError, KeyError, TypeError) as exc:
        raise JudgeReplyError("judge reply is not the expected JSON") from exc
    verdicts: list[Verdict] = []
    for n in range(1, count + 1):
        verdict = found.get(n)
        if verdict not in VERDICTS:
            raise JudgeReplyError(f"statement {n}: missing or unknown verdict")
        verdicts.append(cast(Verdict, verdict))
    return verdicts


class Judge:
    def __init__(self, client: MistralClient, system: str) -> None:
        self._client = client
        self._system = system

    async def judge(
        self, answer: str, citations: Sequence[Citation], chunk_texts: Mapping[str, str]
    ) -> JudgeRecord:
        request = build_request(answer, citations, chunk_texts)
        record = JudgeRecord(excerpt_fallbacks=request.excerpt_fallbacks)
        if not request.statements:
            return record
        try:
            reply = await self._client.judge(self._system, request.passages, request.statements)
        except LLMError as exc:
            record.error = exc.error_code
            return record
        if reply.usage is not None:
            record.tokens_in, record.tokens_out = reply.usage.tokens_in, reply.usage.tokens_out
        try:
            verdicts = parse_verdicts(reply.text, len(request.statements))
        except JudgeReplyError:
            record.error = "judge_unparseable"
            return record
        record.statements = [
            JudgedStatement(text=s.text, markers=s.markers, verdict=v)
            for s, v in zip(request.sentences, verdicts, strict=True)
        ]
        record.faithfulness = faithfulness(verdicts)
        return record
