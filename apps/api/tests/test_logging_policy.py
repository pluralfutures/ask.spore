"""Source-tree policy check: the custom lint rule for logging and cache access.

Fails on, anywhere under app/:
- importing or calling the stdlib ``logging`` module (except app/core/logging.py);
- ``print(...)`` and direct writes to ``sys.stdout`` / ``sys.stderr``;
- ``log(...)`` with a keyword that is not an allow-listed field, or with ``**kwargs``;
- importing ``redis`` (except app/core/cache.py);
- (P1c-04) using a caught ``FetchError`` other than through ``.code`` or ``.status``
  (or handing it to ``_refused``, which answers with the code): its message names the
  URL, so it must never reach a log line, an error text or another exception;
- (P2A-13) using a caught ``RagflowError`` other than through ``.code`` or
  ``.error_code``: its message carries RAGFlow's own text (the detail), so it must never
  reach a log line, an exit message, a source row's error or another exception.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from app.core.logging import ALLOWED_FIELDS

APP_DIR = Path(__file__).resolve().parents[1] / "app"
LOGGING_MODULE = APP_DIR / "core" / "logging.py"
CACHE_MODULE = APP_DIR / "core" / "cache.py"
LOG_KEYWORDS = ALLOWED_FIELDS | {"level"}


def _is_module(node: ast.AST, names: set[str]) -> bool:
    return isinstance(node, ast.Name) and node.id in names


def scan_source(source: str, path: Path) -> list[str]:
    """Return policy violations in one Python source file."""
    tree = ast.parse(source, filename=str(path))
    allow_logging = path == LOGGING_MODULE
    allow_redis = path == CACHE_MODULE
    stdlib_logging_names = {"logging"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.split(".")[0] == "logging" and alias.asname
    }
    violations: list[str] = []

    def report(node: ast.AST, message: str) -> None:
        violations.append(f"{path}:{getattr(node, 'lineno', 0)}: {message}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "logging" and not allow_logging:
                    report(node, "import of stdlib logging; use app.core.logging.log()")
                if root == "redis" and not allow_redis:
                    report(node, "direct redis import; use app.core.cache")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = node.module.split(".")[0]
            if root == "logging" and not allow_logging:
                report(node, "import from stdlib logging; use app.core.logging.log()")
            if root == "redis" and not allow_redis:
                report(node, "direct redis import; use app.core.cache")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print":
                report(node, "print(); use app.core.logging.log()")
            if (
                not allow_logging
                and isinstance(func, ast.Attribute)
                and func.attr == "write"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr in {"stdout", "stderr"}
                and _is_module(func.value.value, {"sys"})
            ):
                report(node, "direct write to sys.stdout/stderr")
            if (
                not allow_logging
                and isinstance(func, ast.Attribute)
                and _is_module(func.value, stdlib_logging_names)
            ):
                module = func.value.id if isinstance(func.value, ast.Name) else "logging"
                report(node, f"{module}.{func.attr}(); use app.core.logging.log()")
            is_log = (isinstance(func, ast.Name) and func.id == "log") or (
                isinstance(func, ast.Attribute) and func.attr == "log"
            )
            if is_log and not (allow_logging and isinstance(func, ast.Attribute)):
                for keyword in node.keywords:
                    if keyword.arg is None:
                        report(node, "log(**kwargs) cannot be checked; pass fields explicitly")
                    elif keyword.arg not in LOG_KEYWORDS:
                        report(node, f"log() field '{keyword.arg}' is not allow-listed")
    return violations


# P1c-04 (independent review, Oct 22, 2026) and P2A-13 (Phase 1c independent review,
# item 3): what a handler of an error whose message must not travel may read, and the
# calls it may hand the error to. A FetchError's message names the URL; a RagflowError's
# carries RAGFlow's own message text.
CODED_ERRORS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # _refused returns HTTPException(detail=exc.code).
    "FetchError": (frozenset({"code", "status"}), frozenset({"_refused"})),
    "RagflowError": (frozenset({"code", "error_code"}), frozenset()),
}
FETCH_ERROR_FIELDS, FETCH_ERROR_SINKS = CODED_ERRORS["FetchError"]


def _caught(handler: ast.ExceptHandler) -> set[str]:
    """The coded error classes ``handler`` catches."""
    if handler.type is None:
        return set()
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names = {
        k.id if isinstance(k, ast.Name) else k.attr
        for k in kinds
        if isinstance(k, ast.Name | ast.Attribute)
    }
    return names & set(CODED_ERRORS)


def scan_coded_errors(source: str, path: Path) -> list[str]:
    """Uses of a caught FetchError or RagflowError other than through their allowed
    attributes or sinks (for a handler catching both, only what both allow)."""
    tree = ast.parse(source, filename=str(path))
    violations: list[str] = []
    for handler in ast.walk(tree):
        if not (isinstance(handler, ast.ExceptHandler) and handler.name):
            continue
        caught = _caught(handler)
        if not caught:
            continue
        fields = frozenset.intersection(*(CODED_ERRORS[c][0] for c in caught))
        sinks = frozenset.intersection(*(CODED_ERRORS[c][1] for c in caught))
        name = handler.name
        allowed: set[int] = set()
        body = ast.Module(body=handler.body, type_ignores=[])
        for node in ast.walk(body):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
                and node.attr in fields
            ):
                allowed.add(id(node.value))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in sinks
            ):
                allowed.update(id(a) for a in node.args if isinstance(a, ast.Name) and a.id == name)
        for node in ast.walk(body):
            if isinstance(node, ast.Name) and node.id == name and id(node) not in allowed:
                kind = " or ".join(sorted(caught))
                violations.append(
                    f"{path}:{node.lineno}: {kind} {name!r} used other than through "
                    f"{', '.join('.' + f for f in sorted(fields))} (its message must not travel)"
                )
    return violations


def scan_fetch_errors(source: str, path: Path) -> list[str]:
    """The P1c-04 rule, now part of ``scan_coded_errors``."""
    return scan_coded_errors(source, path)


def scan_tree(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        violations += scan_source(text, path) + scan_coded_errors(text, path)
    return violations


def test_app_source_tree_follows_logging_and_cache_policy() -> None:
    assert scan_tree(APP_DIR) == []


# The rule itself must catch what it claims to catch.
SOMEWHERE = APP_DIR / "chat" / "example.py"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import logging\nlogging.info('x')\n", "import of stdlib logging"),
        ("import logging as lg\nlg.warning('x')\n", "lg.warning()"),
        ("from logging import getLogger\n", "import from stdlib logging"),
        ("print(answer)\n", "print()"),
        ("import sys\nsys.stderr.write(prompt)\n", "direct write to sys.stdout/stderr"),
        ("log('chat.answer', query=q)\n", "log() field 'query' is not allow-listed"),
        ("log('chat.answer', answer=a)\n", "log() field 'answer' is not allow-listed"),
        ("log('chat.answer', prompt=p)\n", "log() field 'prompt' is not allow-listed"),
        ("log('chat.answer', chunk_text=c)\n", "log() field 'chunk_text' is not allow-listed"),
        ("log('chat.answer', message=m)\n", "log() field 'message' is not allow-listed"),
        ("log('http.request', headers=h)\n", "log() field 'headers' is not allow-listed"),
        ("app_log.log('chat.answer', body=b)\n", "log() field 'body' is not allow-listed"),
        ("log('chat.answer', **fields)\n", "log(**kwargs) cannot be checked"),
        ("import redis\n", "direct redis import"),
        ("from redis.asyncio import Redis\n", "direct redis import"),
    ],
)
def test_policy_rejects(source: str, expected: str) -> None:
    violations = scan_source(source, SOMEWHERE)
    assert any(expected in v for v in violations), violations


def test_policy_allows_allow_listed_log_call() -> None:
    source = (
        "from app.core.logging import log\n"
        "log('chat.answer', level='info', tenant_id=t, latency_ms=12, model=m, status='ok')\n"
    )
    assert scan_source(source, SOMEWHERE) == []


@pytest.mark.parametrize(
    "handler",
    [
        "log('crawl.failed', error_code=str(exc))",
        "log('crawl.failed', error_code=f'{exc}')",
        "log('crawl.failed', status=exc.args[0])",
        "raise IngestError(exc.code, str(exc)) from None",
        "raise SystemExit(f'failed: {exc}') from None",
        "detail = repr(exc)",
        "log('crawl.failed', error_code=exc)",
    ],
)
def test_a_fetch_error_message_never_leaves_its_handler(handler: str) -> None:
    for caught in ("FetchError", "(FetchError, IngestError)", "fetch.FetchError"):
        source = f"try:\n    pass\nexcept {caught} as exc:\n    {handler}\n"
        assert scan_fetch_errors(source, SOMEWHERE), (caught, handler)


@pytest.mark.parametrize(
    "handler",
    [
        "log('crawl.failed', error_code=exc.code)",
        "return Visit(url, 'missing', f'http_{exc.status}')",
        "raise _refused(exc) from None",
        "raise SystemExit(f'ask-spore crawl: {exc.code}') from None",
    ],
)
def test_a_fetch_error_handler_may_use_the_code_and_status(handler: str) -> None:
    source = f"try:\n    pass\nexcept FetchError as exc:\n    {handler}\n"
    assert scan_fetch_errors(source, SOMEWHERE) == []
    # Other exceptions are not this rule's business.
    other = "try:\n    pass\nexcept IngestError as exc:\n    raise SystemExit(str(exc))\n"
    assert scan_fetch_errors(other, SOMEWHERE) == []


# --- P2A-05, P2A-08: response schemas that must carry no body ------------------------------
# As for log fields: every field name of these responses is on an allow-list, so a new
# field fails here until it is classified; and none of them can carry a body or a
# per-user identifier.

BODY_FIELDS = frozenset(
    {
        "query",
        "question",
        "answer",
        "prompt",
        "message",
        "messages",
        "chunk_text",
        "excerpt",
        "content",
        "text",
        "body",
        "conversation_id",
        "message_id",
        "user_id",
        "actor_user_id",
        "email",
        "headers",
        "token",
    }
)


def schema_fields(model: type[Any]) -> set[str]:
    """Every property name in a pydantic model's JSON schema, nested models included."""
    schema = model.model_json_schema()
    names: set[str] = set()
    for part in [schema, *schema.get("$defs", {}).values()]:
        names |= set(part.get("properties", {}))
    return names


USAGE_FIELDS = frozenset(
    {
        "since",
        "until",
        "questions",
        "active_users",
        "top_sources",
        "cost_month",
        "costs",
        "day",
        "mode",
        "users",
        "title",
        "publisher",
        "answers",
        "model",
        "display_name",
        "external",
        "tokens_in",
        "tokens_out",
        "cost_cents",
    }
)


def test_the_usage_response_carries_counts_only() -> None:
    from app.api.schemas import UsageOut

    fields = schema_fields(UsageOut)
    assert fields == USAGE_FIELDS, sorted(fields ^ USAGE_FIELDS)
    assert not USAGE_FIELDS & BODY_FIELDS


# P2A-08: the support view. The operator reads a conversation's text through a grant;
# none of it may reach a log line, an audit event or an exception. In the support module
# every log() carries identifiers and codes only, every record() a literal mapping of
# identifiers, and every raised exception a constant (or nothing).
SUPPORT_MODULE = APP_DIR / "support" / "access.py"
SUPPORT_LOG_FIELDS = frozenset({"level", "tenant_id", "grant_id", "status", "error_code"})
SUPPORT_AUDIT_KEYS = frozenset(
    {"operator_id", "grant_id", "scope", "conversation_id", "duration_minutes"}
)


def scan_support(source: str, path: Path) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name == "log":
                for keyword in node.keywords:
                    if keyword.arg not in SUPPORT_LOG_FIELDS:
                        violations.append(f"{node.lineno}: log() field {keyword.arg!r}")
            if name == "record":
                metadata = next((k.value for k in node.keywords if k.arg == "metadata"), None)
                if not isinstance(metadata, ast.Dict) or None in metadata.keys:
                    violations.append(f"{node.lineno}: record() metadata is not a literal mapping")
                    continue
                for key in metadata.keys:
                    if not (isinstance(key, ast.Constant) and key.value in SUPPORT_AUDIT_KEYS):
                        violations.append(f"{node.lineno}: record() key {ast.unparse(key)}")  # type: ignore[arg-type]
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for arg in node.exc.args:
                if not isinstance(arg, ast.Constant):
                    violations.append(f"{node.lineno}: raise with {ast.unparse(arg)}")
    return violations


def test_the_support_view_logs_and_audits_identifiers_only() -> None:
    assert scan_support(SUPPORT_MODULE.read_text(encoding="utf-8"), SUPPORT_MODULE) == []


@pytest.mark.parametrize(
    "line",
    [
        "log('operator.support_viewed', tenant_id=t, message=m.content)",
        "log('operator.support_viewed', count=len(body))",
        "await record(s, tenant_id=t, actor_user_id=None, event='e', metadata={'note': n})",
        "await record(s, tenant_id=t, actor_user_id=None, event='e', metadata=values)",
        "raise GrantRefused(f'bad {text}')",
        "raise SupportNotFound(row.content)",
    ],
)
def test_the_support_scan_rejects(line: str) -> None:
    assert scan_support(f"async def f():\n    {line}\n", SUPPORT_MODULE)


SUPPORT_GRANT_FIELDS = frozenset(
    {
        "id",
        "scope",
        "conversation_id",
        "conversation_title",
        "duration_minutes",
        "note",
        "created_at",
        "expires_at",
        "revoked_at",
        "state",
        "views",
        "last_viewed_at",
    }
)


def test_support_grant_lists_carry_no_body_and_no_user() -> None:
    from app.api.schemas import OperatorSupportGrantOut, SupportGrantOut

    for model in (SupportGrantOut, OperatorSupportGrantOut):
        fields = schema_fields(model)
        assert fields <= SUPPORT_GRANT_FIELDS, sorted(fields - SUPPORT_GRANT_FIELDS)
    assert not SUPPORT_GRANT_FIELDS & (BODY_FIELDS - {"conversation_id"})


def test_the_support_view_names_no_user() -> None:
    """The view shows a conversation as its user sees it, never who the user is."""
    from app.api.schemas import SupportConversationOut, SupportSettingsOut

    for model in (SupportConversationOut, SupportSettingsOut):
        fields = schema_fields(model)
        assert not fields & {"user_id", "actor_user_id", "email", "display_name", "user"}
        assert not fields & {"conversation_id", "message_id", "id"}
# --- P2A-13: RagflowError handlers -------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        "log('ingest.failed', error_code=str(exc))",
        "log('ingest.failed', error_code=f'{exc}')",
        "log('ingest.failed', status=exc.args[0])",
        "log('ingest.failed', error_code=exc)",
        "failure = _Failure(exc.error_code, str(exc))",
        "raise _Failure(exc.error_code, f'clean-up failed: {exc}') from None",
        "error += f'documents left in RAGFlow: {exc}'",
        "raise SystemExit(f'ask-spore ingest: {exc}') from None",
        "return IngestResult(source_id, 'failed', error=repr(exc))",
        "detail = exc.detail",
        "raise _refused(exc) from None",
    ],
)
def test_a_ragflow_error_message_never_leaves_its_handler(handler: str) -> None:
    for caught in ("RagflowError", "(RagflowError, OSError)", "ragflow.RagflowError"):
        source = f"try:\n    pass\nexcept {caught} as exc:\n    {handler}\n"
        assert scan_coded_errors(source, SOMEWHERE), (caught, handler)


def test_a_handler_of_both_coded_errors_may_use_only_what_both_allow() -> None:
    both = "try:\n    pass\nexcept (FetchError, RagflowError) as exc:\n    {}\n"
    assert scan_coded_errors(both.format("log('x', status=exc.status)"), SOMEWHERE)
    assert scan_coded_errors(both.format("log('x', error_code=exc.error_code)"), SOMEWHERE)
    assert scan_coded_errors(both.format("log('x', error_code=exc.code)"), SOMEWHERE) == []


@pytest.mark.parametrize(
    "handler",
    [
        "log('ingest.failed', error_code=exc.error_code)",
        "failure = _Failure(exc.error_code)",
        "raise _Failure(exc.error_code, 'clean-up of an interrupted run') from None",
        "return exc.code in ('not_found', 404)",
        "raise",
        "raise HTTPException(502, detail='ragflow_unavailable') from None",
    ],
)
def test_a_ragflow_error_handler_may_use_the_code(handler: str) -> None:
    source = f"try:\n    pass\nexcept RagflowError as exc:\n    {handler}\n"
    assert scan_coded_errors(source, SOMEWHERE) == []


def test_every_ragflow_error_handler_in_the_app_is_scanned() -> None:
    """Every RagflowError handler in the app (ingest, withdraw, the content API,
    retrieval: nine today) is found by the scan, and none is a violation."""
    seen = 0
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        handlers = [
            h
            for h in ast.walk(tree)
            if isinstance(h, ast.ExceptHandler) and "RagflowError" in _caught(h)
        ]
        seen += len(handlers)
        assert scan_coded_errors(path.read_text(encoding="utf-8"), path) == [], path
    assert seen >= 9
