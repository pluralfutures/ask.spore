import json

import pytest

from app.core.logging import ALLOWED_FIELDS, ForbiddenLogField, format_line, log


@pytest.mark.parametrize(
    "field", ["query", "answer", "prompt", "chunk_text", "message", "body", "headers", "token"]
)
def test_forbidden_field_raises(field: str) -> None:
    with pytest.raises(ForbiddenLogField, match=field):
        log("chat.answer", **{field: "some text"})


def test_forbidden_field_raises_even_with_allowed_fields() -> None:
    with pytest.raises(ForbiddenLogField, match="query"):
        log("chat.answer", tenant_id="t1", query="what is the outlook?")


def test_allow_list_matches_spec() -> None:
    assert ALLOWED_FIELDS == {
        "request_id",
        "tenant_id",
        "user_id",
        "conversation_id",
        "message_id",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "model",
        "status",
        "source_id",
        "chunk_count",
        "error_code",
        "tag",
        "dataset_id",
        "document_id",
        "manifest_line",
        "count",
        "route",
        "method",
        "exception",
        "job_id",
        "job_type",
        "attempts",
        "site_id",
        "template",
        "consent_version",
        "grant_id",
        "table",
        "certificate",
        "reasoning_tokens",
    }


def test_site_id_takes_a_scalar_only() -> None:
    # P1b-04: a site is logged by its ID; a mapping (e.g. its settings) is refused.
    assert json.loads(format_line("job.finished", site_id="s1"))["site_id"] == "s1"
    with pytest.raises(ForbiddenLogField):
        log("job.finished", site_id={"start_url": "https://example.org/"})  # type: ignore[arg-type]


def test_allowed_fields_render_as_one_json_line() -> None:
    line = format_line(
        "chat.answer", tenant_id="t1", latency_ms=42, tokens_in=10, status="ok", model=None
    )
    record = json.loads(line)
    assert "\n" not in line
    assert record["event"] == "chat.answer"
    assert record["level"] == "info"
    assert record["latency_ms"] == 42
    assert set(record) == {"ts", "level", "event", "tenant_id", "latency_ms", "tokens_in"} | {
        "status",
        "model",
    }


def test_log_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    log("api.started", status="ok")
    out = capsys.readouterr().out
    assert json.loads(out)["event"] == "api.started"


def test_non_scalar_value_rejected() -> None:
    with pytest.raises(ForbiddenLogField, match="scalar"):
        log("chat.answer", status={"query": "leak"})  # type: ignore[arg-type]


def test_long_string_value_rejected() -> None:
    # An allowed field cannot be used to smuggle a body.
    with pytest.raises(ForbiddenLogField, match="exceeds"):
        log("chat.answer", error_code="x" * 500)


@pytest.mark.parametrize("event", ["", "Chat Answer", "user asked: what is GDP?", "a" * 200])
def test_event_must_be_identifier(event: str) -> None:
    with pytest.raises(ForbiddenLogField, match="event"):
        log(event)


def test_log_line_contains_no_body_text() -> None:
    body = "What did the 2025 report conclude about Germany?"
    with pytest.raises(ForbiddenLogField):
        format_line("chat.answer", tenant_id="t1", query=body)
    line = format_line("chat.answer", tenant_id="t1", chunk_count=3)
    assert body not in line
