"""P0-18: the full pipeline through the API's SSE stream."""

from __future__ import annotations

import json
from typing import Any

import httpx

from eval.pipeline import ApiPipeline

CONVERSATION = "7d1f0e7a-1111-4c2b-9e1f-0a1b2c3d4e5f"
CITATION = {
    "marker": 1,
    "source_id": "3f2b8c1e-7d4a-4c2b-9e1f-0a1b2c3d4e5f",
    "chunk_id": "c1",
    "page_or_slide": 2,
    "excerpt": "Installed capacity reached 4.2 GW.",
    "publisher": "Synthetic Institute",
    "title": "Synthetic Outlook",
    "published_on": "2026-03-02",
    "canonical_url": "https://example.org/a",
    "type": "pdf",
}


def frames(*events: tuple[str, dict[str, Any]]) -> bytes:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def done(**flags: Any) -> tuple[str, dict[str, Any]]:
    data = {
        "message_id": "m1",
        "unsupported": False,
        "abstained": False,
        "cached": False,
        "tokens_in": 120,
        "tokens_out": 30,
    }
    return "done", data | flags


class FakeApi:
    def __init__(self, stream: bytes, status: int = 200) -> None:
        self.stream = stream
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/conversations":
            return httpx.Response(201, json={"id": CONVERSATION})
        if request.method == "POST" and path.endswith("/messages"):
            return httpx.Response(
                self.status, headers={"content-type": "text/event-stream"}, content=self.stream
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"status": "ok"})


def pipeline(api: FakeApi) -> ApiPipeline:
    return ApiPipeline(
        "http://api.test/",
        "token-0123456789",
        "eval@example.org",
        transport=httpx.MockTransport(api),
    )


async def test_answer_citations_and_outcome_are_read_from_the_stream() -> None:
    api = FakeApi(
        frames(
            ("token", {"text": "Capacity reached "}),
            ("token", {"text": "4.2 GW [1]."}),
            ("citations", {"citations": [CITATION]}),
            done(),
        )
    )
    result = await pipeline(api).ask("What capacity?")
    assert result.outcome == "answered"
    assert result.answer == "Capacity reached 4.2 GW [1]."
    assert [(c.marker, c.chunk_id, c.canonical_url) for c in result.citations] == [
        (1, "c1", "https://example.org/a")
    ]
    assert (result.tokens_in, result.tokens_out, result.cached) == (120, 30, False)
    # A fresh conversation per question, deleted afterwards; Phase 0 auth headers.
    methods = [(r.method, r.url.path) for r in api.requests]
    assert methods == [
        ("POST", "/api/v1/conversations"),
        ("POST", f"/api/v1/conversations/{CONVERSATION}/messages"),
        ("DELETE", f"/api/v1/conversations/{CONVERSATION}"),
    ]
    assert json.loads(api.requests[1].content) == {"question": "What capacity?"}
    assert all(r.headers["authorization"] == "Bearer token-0123456789" for r in api.requests)
    assert all(r.headers["x-user-email"] == "eval@example.org" for r in api.requests)


async def test_abstained_unsupported_and_cached() -> None:
    abstained = FakeApi(
        frames(
            ("token", {"text": "Nothing."}), ("citations", {"citations": []}), done(abstained=True)
        )
    )
    assert (await pipeline(abstained).ask("q")).outcome == "abstained"
    unsupported = FakeApi(
        frames(("citations", {"citations": []}), done(unsupported=True, cached=True))
    )
    result = await pipeline(unsupported).ask("q")
    assert (result.outcome, result.cached) == ("unsupported", True)


async def test_error_event_incomplete_stream_and_http_errors() -> None:
    errored = await pipeline(FakeApi(frames(("error", {"error_code": "llm_timeout"})))).ask("q")
    assert (errored.outcome, errored.error_code) == ("error", "llm_timeout")

    cut = await pipeline(FakeApi(frames(("token", {"text": "Half"})))).ask("q")
    assert (cut.outcome, cut.error_code) == ("error", "stream_incomplete")

    api = FakeApi(b"", status=503)
    failed = await pipeline(api).ask("q")
    assert (failed.outcome, failed.error_code) == ("error", "http_503")
    assert api.requests[-1].method == "DELETE"  # cleaned up even on failure


async def test_oidc_path_signs_a_fresh_service_credential_per_request() -> None:
    # P1b-15 a: with the service key, no Phase 0 headers; each request carries an
    # EdDSA credential the API's EvalServiceValidator accepts for the service identity.
    from app.auth.eval_service import EvalServiceValidator, generate_key_pair

    private, public = generate_key_pair()
    api = FakeApi(
        frames(("token", {"text": "Grew [1]."}), ("citations", {"citations": []}), done())
    )
    oidc = ApiPipeline(
        "http://api.test/",
        "",
        "eval-service@example.org",
        transport=httpx.MockTransport(api),
        service_key=private,
    )
    await oidc.check()
    result = await oidc.ask("What grew?")
    assert result.outcome == "answered"
    validator = EvalServiceValidator(public, "eval-service@example.org", 900)
    tokens = []
    for request in api.requests:
        assert "x-user-email" not in request.headers
        scheme, token = request.headers["authorization"].split(" ")
        assert scheme == "Bearer"
        assert validator.validate(token).email == "eval-service@example.org"
        tokens.append(token)
    assert [r.url.path for r in api.requests][:2] == ["/api/v1/healthz", "/api/v1/me"]
    assert len(set(tokens)) == len(tokens)  # never reused


def test_keygen_writes_a_private_key_only_its_owner_reads(tmp_path: Any) -> None:
    import stat

    from eval.cli import main

    assert main(["keygen", "--out-dir", str(tmp_path)]) == 0
    key = tmp_path / "eval-service.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert "PUBLIC KEY" in (tmp_path / "eval-service.pub").read_text()
    try:
        main(["keygen", "--out-dir", str(tmp_path)])
    except FileExistsError:
        pass
    else:
        raise AssertionError("keygen overwrote an existing key")
