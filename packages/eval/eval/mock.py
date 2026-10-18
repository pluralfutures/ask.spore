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

import httpx

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
