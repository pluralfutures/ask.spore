"""Source-tree policy check: the custom lint rule for logging and cache access.

Fails on, anywhere under app/:
- importing or calling the stdlib ``logging`` module (except app/core/logging.py);
- ``print(...)`` and direct writes to ``sys.stdout`` / ``sys.stderr``;
- ``log(...)`` with a keyword that is not an allow-listed field, or with ``**kwargs``;
- importing ``redis`` (except app/core/cache.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

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


def scan_tree(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        violations += scan_source(path.read_text(encoding="utf-8"), path)
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
