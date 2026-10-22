"""Metadata-only structured logging.

The only way application code logs. ``log(event, **fields)`` accepts an
allow-listed set of field names and scalar values, and writes one JSON line to
stdout. Request and response bodies, queries, answers, prompts and chunk text can
never be passed: there is no field for them, and string values are length-capped
so an allowed field cannot smuggle a body.

Direct use of the ``logging`` module, ``print`` or ``log()`` with any other field
name elsewhere in ``app/`` is rejected by tests/test_logging_policy.py.
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
import re
import sys
from datetime import UTC, datetime
from typing import Final, Literal

ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
        # Shared-corpus identifiers for the content CLIs (P0-08 to P0-10): never bodies.
        "tag",
        "dataset_id",
        "document_id",
        # Batch ingestion summary (P0-11): manifest line number and a row count.
        "manifest_line",
        "count",
        # Last-resort error line (findings §12): the route template, never the raw path
        # (a download path carries a token), the method and the exception class name.
        "route",
        "method",
        "exception",
        # Job queue (P1b-02): which job, its type and how many attempts it has taken.
        "job_id",
        "job_type",
        "attempts",
        # Crawl management (P1b-04): which registered site (an identifier, never its URL).
        "site_id",
    }
)

MAX_STRING_LENGTH: Final = 128
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")

Level = Literal["debug", "info", "warning", "error"]
LogValue = str | int | float | bool | None

_LEVELS: Final[dict[Level, int]] = {
    "debug": _stdlib_logging.DEBUG,
    "info": _stdlib_logging.INFO,
    "warning": _stdlib_logging.WARNING,
    "error": _stdlib_logging.ERROR,
}


class ForbiddenLogField(ValueError):
    """A log call used a field name, value type or event name that is not allowed."""


class _StdoutHandler(_stdlib_logging.Handler):
    """Writes each record to the current ``sys.stdout`` (resolved at emit time)."""

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def _build_logger() -> _stdlib_logging.Logger:
    logger = _stdlib_logging.getLogger("ask_spore")
    if not logger.handlers:
        handler = _StdoutHandler()
        handler.setFormatter(_stdlib_logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(_stdlib_logging.INFO)
    logger.propagate = False
    return logger


_logger: Final = _build_logger()


def _validate(event: str, fields: dict[str, LogValue]) -> None:
    if not _EVENT_NAME.fullmatch(event) or len(event) > MAX_STRING_LENGTH:
        raise ForbiddenLogField("event must be a short dotted identifier such as 'chat.answer'")
    forbidden = sorted(set(fields) - ALLOWED_FIELDS)
    if forbidden:
        raise ForbiddenLogField(f"log field(s) not allow-listed: {', '.join(forbidden)}")
    for name, value in fields.items():
        if not isinstance(value, str | int | float | bool | None):
            raise ForbiddenLogField(f"log field '{name}' must be a scalar")
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            raise ForbiddenLogField(f"log field '{name}' exceeds {MAX_STRING_LENGTH} characters")


def format_line(event: str, level: Level = "info", **fields: LogValue) -> str:
    """Validate and render one log line without emitting it."""
    _validate(event, fields)
    record: dict[str, LogValue] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        **fields,
    }
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def silence_library_loggers(*names: str) -> None:
    """Mute third-party loggers that can write request bodies (e.g. ``openai`` when
    OPENAI_LOG=debug). Only this module may touch the stdlib logging module."""
    for name in names:
        logger = _stdlib_logging.getLogger(name)
        logger.setLevel(_stdlib_logging.CRITICAL + 1)
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(_stdlib_logging.NullHandler())


def log(event: str, level: Level = "info", **fields: LogValue) -> None:
    """Write a metadata-only JSON log line. Raises ForbiddenLogField on any other field."""
    _logger.log(_LEVELS[level], format_line(event, level, **fields))
