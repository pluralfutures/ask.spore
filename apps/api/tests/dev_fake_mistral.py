"""Dev only: run the API against the real RAGFlow with Mistral mocked at the HTTP layer.

For an end-to-end pass without a Mistral key (phase-0-findings.md, "Integration").
Everything is real except the transport under ``app.llm.mistral.MistralClient``:
RAGFlow retrieval, the provenance join, citation mapping, persistence and audit.

    uv run python -m tests.dev_fake_mistral --port 8001

The environment needs what the API needs (MISTRAL_API_KEY may be any value). The
fake model answers from the passages it is given: the first sentence of passages
1 and 2 with their markers, plus a dangling marker the orchestrator must drop. It
prints, per request, only the passage count and whether anything shaped like an
identifier (UUID or 32-hex ID) reached it; never the prompt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import partial
from typing import Any

import httpx
import pytest
import uvicorn

from app import main
from app.llm.mistral import MistralClient
from app.retrieval.ragflow import RagflowRetriever
from tests.fakes import completion, delta, sse

_PASSAGE = re.compile(r'<passage n="(\d+)"[^>]*>\n(.*?)\n</passage>', re.S)
_IDENTIFIER = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{32}\b", re.I
)
_USAGE = {"prompt_tokens": 0, "completion_tokens": 0}


def _first_sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    return sentence[:160].rstrip(".") + "."


def _answer(prompt: str) -> list[str]:
    passages = _PASSAGE.findall(prompt)
    parts = [f"{_first_sentence(text)} [{n}]" for n, text in passages[:2]]
    return [*(p + " " for p in parts), f"An unsupported aside [{len(passages) + 5}]."]


def handler(request: httpx.Request) -> httpx.Response:
    body: dict[str, Any] = json.loads(request.content)
    raw = json.dumps(body)
    last = body["messages"][-1]["content"]
    report = {
        "fake_mistral": "stream" if body.get("stream") else "complete",
        "passages": len(_PASSAGE.findall(last)),
        "identifier_shaped_strings": len(_IDENTIFIER.findall(raw)),
    }
    sys.stderr.write(json.dumps(report) + "\n")
    if not body.get("stream"):
        return completion(last)  # rewrite: the question is its own standalone query
    return sse(*(delta(part) for part in _answer(last)), delta("", _USAGE))


def run(host: str, port: int) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    pytest.MonkeyPatch().setattr(main, "MistralClient", partial(MistralClient, http_client=http))
    uvicorn.run(main.create_app(retriever=RagflowRetriever()), host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    run(args.host, args.port)
