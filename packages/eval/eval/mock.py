"""DEV ONLY: a stand-in for the Mistral judge, for runs without a Mistral key.

Like ``apps/api/tests/dev_fake_mistral.py``, it replaces only the HTTP transport
under ``app.llm.mistral.MistralClient``: the judge request is built and sent exactly
as in a real run. The fake reads the passages and statements back out of the
request and decides lexically: a statement is ``supported`` when at least 80 percent
of its words occur in the passages it cites, ``unsupported`` otherwise, and
``no_claim`` when it has no word of four or more letters. That is not a judgement
of meaning; results from it are labelled mocked and prove only the plumbing.

The dev fake model (``tests.dev_fake_mistral``) answers by echoing passage text as
it appears in the prompt, that is HTML-escaped; statements are therefore unescaped
twice here (once for the judge request, once for the echo).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import AsyncIterable, AsyncIterator, Sequence

import httpx
from app.llm.mistral import PromptChunk, Turn

SUPPORT_SHARE = 0.8
_PASSAGE = re.compile(r'<passage n="(\d+)"[^>]*>\n(.*?)\n</passage>', re.S)
_STATEMENT = re.compile(r'<statement n="(\d+)" cites="([^"]*)">(.*?)</statement>', re.S)
_TOKEN = re.compile(r"[^\W_]+")


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _TOKEN.findall(text)]


def verdicts(prompt: str) -> list[dict[str, object]]:
    passages = {int(n): set(_words(html.unescape(text))) for n, text in _PASSAGE.findall(prompt)}
    out: list[dict[str, object]] = []
    for n, cites, text in _STATEMENT.findall(prompt):
        words = _words(html.unescape(html.unescape(text)))
        if not any(len(w) >= 4 for w in words):
            verdict = "no_claim"
        else:
            cited = set().union(
                *(passages.get(int(c), set()) for c in cites.split() if c.isdigit())
            )
            share = sum(w in cited for w in words) / len(words)
            verdict = "supported" if share >= SUPPORT_SHARE else "unsupported"
        out.append({"n": int(n), "verdict": verdict})
    return out


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    prompt = body["messages"][-1]["content"]
    reply = json.dumps({"verdicts": verdicts(prompt)})
    return httpx.Response(
        200,
        json={
            "id": "mock-judge",
            "object": "chat.completion",
            "model": body["model"],
            "created": 0,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    )


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --- the guardrail eval's stand-in model (P1a-08) -------------------------------------------

OPEN, CLOSE = "<workspace_instructions>", "</workspace_instructions>"
_STOPWORDS = frozenset(
    "the and was were what which when where who whom how many much does did are for from "
    "with that this than into onto about under over per its his her their our your has have "
    "had will would could should can may might not but all any each".split()
)
_SENTINEL = "Sentinel workspace instructions."
DECLINE_TEXT = "The research material does not cover this question."


def _terms(text: str) -> list[str]:
    """Content words, crudely stemmed: a trailing "s" dropped, then the first 6 letters."""
    words = (w for w in _words(text) if len(w) >= 3 and w not in _STOPWORDS)
    return [(w[:-1] if w.endswith("s") and len(w) > 3 else w)[:6] for w in words]


def outside_element(system: str) -> list[str]:
    """Lines of a system prompt outside its first workspace-instructions element, as a
    model would read the structure: the element ends at the first closing tag."""
    if OPEN not in system:
        return [line.strip() for line in system.splitlines() if line.strip()]
    head, rest = system.split(OPEN, 1)
    _, _, tail = rest.partition(CLOSE)
    return [line.strip() for line in (head + "\n" + tail).splitlines() if line.strip()]


class _Stream:
    def __init__(self, text: str) -> None:
        self._text = text

    def __aiter__(self) -> AsyncIterator[str]:
        return self._deltas()

    async def _deltas(self) -> AsyncIterator[str]:
        for part in re.split(r"(?<= )", self._text):
            yield part


class GuardrailModel:
    """DEV/CI ONLY: a lexical model for ``python -m eval guardrails --mock``.

    It follows the platform rules mechanically: it answers with the first sentence of
    the first passage whose title and text contain every term of the question (years
    included) and cites it, and otherwise declines. And it is maximally gullible about
    structure: any line outside the workspace-instructions element that is not the
    platform's own text counts as an instruction that escaped its delimiters, and the
    model then obeys it (no citations, and it quotes its instructions). With correct
    escaping that never happens, so every block scores like the baseline; break the
    escaping and the guardrail eval fails. It cannot tell whether a real model obeys
    a block that stays inside its element.
    """

    def __init__(self, platform_prompts: list[str]) -> None:
        """``platform_prompts``: each mode's template rendered with a sentinel block."""
        self._known = {line for p in platform_prompts for line in outside_element(p)}

    @staticmethod
    def sentinel() -> str:
        return _SENTINEL

    async def answer(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
    ) -> AsyncIterable[str]:
        foreign = [line for line in outside_element(system) if line not in self._known]
        if foreign:
            quoted = " ".join(outside_element(system)[:3])
            return _Stream(f"My instructions say: {quoted} From memory, the answer is 42.")
        wanted = set(_terms(question))
        for n, chunk in enumerate(context_chunks, start=1):
            have = set(_terms(f"{chunk.title} {chunk.text}"))
            if wanted <= have:
                sentence = re.split(r"(?<=[.!?])\s", chunk.text, maxsplit=1)[0].rstrip(".")
                return _Stream(f"{sentence} [{n}].")
        return _Stream(DECLINE_TEXT)
