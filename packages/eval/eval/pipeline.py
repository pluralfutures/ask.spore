"""The full pipeline through the API under test (P0-18).

Each question is asked as the first message of a new conversation, exactly as the
web app does (``POST /api/v1/conversations``, then the SSE stream of
``POST /api/v1/conversations/{id}/messages``); the conversation is hard-deleted
afterwards. Authentication, by what the environment gives the harness:

- under ``[auth] mode = "oidc"`` (P1b-15 a): a credential signed with the eval
  service's private key for the service identity (``app.auth.eval_service``), a fresh
  one per request, so a long run never outlives a credential;
- under ``mode = "phase0"``: the shared bearer token plus ``X-User-Email`` of a seeded
  internal user.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from app.auth.eval_service import sign_credential

from eval.records import Outcome

STREAM_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class Citation:
    """A citation from the ``citations`` event. ``excerpt`` is kept in memory only."""

    marker: int
    chunk_id: str
    source_id: str
    canonical_url: str | None
    publisher: str
    title: str
    published_on: str | None
    page_or_slide: int | None
    type: str
    excerpt: str


@dataclass
class PipelineAnswer:
    outcome: Outcome = "error"
    error_code: str | None = None
    answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """``(event, data)`` pairs from a Server-Sent Events line stream."""
    event = "message"
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].strip())
    if data:
        yield event, json.loads("\n".join(data))


def _citation(raw: dict[str, Any]) -> Citation:
    return Citation(
        marker=int(raw["marker"]),
        chunk_id=str(raw["chunk_id"]),
        source_id=str(raw["source_id"]),
        canonical_url=raw.get("canonical_url"),
        publisher=str(raw.get("publisher", "")),
        title=str(raw.get("title", "")),
        published_on=raw.get("published_on"),
        page_or_slide=raw.get("page_or_slide"),
        type=str(raw.get("type", "")),
        excerpt=str(raw.get("excerpt", "")),
    )


async def read_stream(events: AsyncIterator[tuple[str, dict[str, Any]]]) -> PipelineAnswer:
    result = PipelineAnswer()
    parts: list[str] = []
    finished = False
    async for name, data in events:
        if name == "token":
            parts.append(str(data["text"]))
        elif name == "citations":
            result.citations = [_citation(c) for c in data["citations"]]
        elif name == "done":
            finished = True
            if data.get("abstained"):
                result.outcome = "abstained"
            elif data.get("unsupported"):
                result.outcome = "unsupported"
            else:
                result.outcome = "answered"
            result.cached = bool(data.get("cached"))
            result.tokens_in = int(data.get("tokens_in") or 0)
            result.tokens_out = int(data.get("tokens_out") or 0)
        elif name == "error":
            result.error_code = str(data.get("error_code") or "stream_error")
            return result
    result.answer = "".join(parts)
    if not finished:
        result.outcome, result.error_code = "error", "stream_incomplete"
    return result


class ServiceCredential(httpx.Auth):
    """Signs a short-lived eval service credential for every request (P1b-15 a)."""

    def __init__(self, private_key_pem: str, email: str, lifetime_seconds: int = 300) -> None:
        self._key = private_key_pem
        self._email = email
        self._lifetime = lifetime_seconds

    def auth_flow(self, request: httpx.Request) -> Any:
        token = sign_credential(self._key, self._email, lifetime_seconds=self._lifetime)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class ApiPipeline:
    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        user_email: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        service_key: str | None = None,
    ) -> None:
        """``service_key`` (the eval service's private key) selects the oidc path;
        otherwise ``bearer_token`` is the Phase 0 token."""
        auth: httpx.Auth | None = None
        headers: dict[str, str] = {}
        if service_key:
            auth = ServiceCredential(service_key, user_email)
        else:
            headers = {"Authorization": f"Bearer {bearer_token}", "X-User-Email": user_email}
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            auth=auth,
            timeout=httpx.Timeout(30.0, read=STREAM_TIMEOUT_SECONDS),
            transport=transport,
            follow_redirects=False,
        )
        # The workspace conversations start in (P1a-04); set from the retrieval step.
        self.workspace_id: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> None:
        """Fail early, before any item, if the API is unreachable or rejects us."""
        response = await self._http.get("/api/v1/healthz")
        response.raise_for_status()
        # healthz is public; /me proves the credential is accepted.
        response = await self._http.get("/api/v1/me")
        response.raise_for_status()

    async def ask(self, question: str) -> PipelineAnswer:
        started = time.perf_counter()
        try:
            body = {"workspace_id": self.workspace_id} if self.workspace_id else None
            created = await self._http.post("/api/v1/conversations", json=body)
            created.raise_for_status()
            conversation_id = created.json()["id"]
            try:
                async with self._http.stream(
                    "POST",
                    f"/api/v1/conversations/{conversation_id}/messages",
                    json={"question": question},
                ) as response:
                    response.raise_for_status()
                    result = await read_stream(parse_sse(response.aiter_lines()))
            finally:
                await self._http.delete(f"/api/v1/conversations/{conversation_id}")
        except httpx.HTTPStatusError as exc:
            result = PipelineAnswer(error_code=f"http_{exc.response.status_code}")
        except httpx.HTTPError:
            result = PipelineAnswer(error_code="api_unreachable")
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result
