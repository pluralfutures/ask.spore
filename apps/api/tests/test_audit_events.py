"""P2A-07: the audit event catalogue and the tenant admin's export.

The catalogue test scans the source tree for every event name passed to
``app.audit.writer.record``, directly or through a helper that forwards its own
``event`` argument (``audit_sign_in``, the register's ``_audit``), and fails on a name
that ``app.audit.events`` does not classify as exported or operator-only. Negative
cases first."""

from __future__ import annotations

import ast
import asyncio
import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api import admin as admin_routes
from app.audit.events import (
    AUDIT_EVENTS,
    DYNAMIC_EVENTS,
    EXPORTED_EVENTS,
    OPERATOR_ONLY_EVENTS,
)
from app.audit.writer import UnclassifiedAuditEvent, record

APP_DIR = Path(__file__).resolve().parents[1] / "app"
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _params(fn: FunctionNode) -> tuple[list[str], list[str]]:
    positional = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if positional and positional[0] in {"self", "cls"}:
        positional = positional[1:]
    return positional, [a.arg for a in fn.args.kwonlyargs]


def _event_args(call: ast.Call, helpers: dict[str, int | None]) -> list[ast.expr]:
    index = helpers[_callee(call) or ""]
    values = [k.value for k in call.keywords if k.arg == "event"]
    if index is not None and len(call.args) > index:
        values.append(call.args[index])
    return values


def _functions(trees: dict[Path, ast.Module]) -> list[tuple[Path, FunctionNode]]:
    return [
        (path, fn)
        for path, tree in trees.items()
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def audit_helpers(trees: dict[Path, ast.Module]) -> dict[str, int | None]:
    """``record`` and every function that passes its own ``event`` parameter on to it
    (or to another such helper): name to the parameter's positional index."""
    helpers: dict[str, int | None] = {"record": None}
    changed = True
    while changed:
        changed = False
        for _, fn in _functions(trees):
            if fn.name in helpers:
                continue
            positional, keyword = _params(fn)
            if "event" not in positional + keyword:
                continue
            forwards = any(
                isinstance(arg, ast.Name) and arg.id == "event"
                for call in ast.walk(fn)
                if isinstance(call, ast.Call) and _callee(call) in helpers
                for arg in _event_args(call, helpers)
            )
            if forwards:
                helpers[fn.name] = positional.index("event") if "event" in positional else None
                changed = True
    return helpers


def _loop_values(fn: FunctionNode, name: str) -> list[ast.expr] | None:
    """The values a ``for`` loop binds to ``name`` from a literal list of tuples assigned
    in the same function, or None when they cannot be read statically."""
    lists = {
        target.id: node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and isinstance(node.value, ast.List | ast.Tuple)
    }
    for loop in ast.walk(fn):
        if not (isinstance(loop, ast.For | ast.AsyncFor) and isinstance(loop.target, ast.Tuple)):
            continue
        names = [t.id if isinstance(t, ast.Name) else None for t in loop.target.elts]
        if name not in names:
            continue
        source = lists.get(loop.iter.id) if isinstance(loop.iter, ast.Name) else loop.iter
        if not isinstance(source, ast.List | ast.Tuple):
            return None
        position = names.index(name)
        values = []
        for item in source.elts:
            if not isinstance(item, ast.Tuple):
                return None
            values.append(item.elts[position])
        return values
    return None


def scan_events(sources: dict[Path, str]) -> tuple[set[str], list[str]]:
    """Every audit event name the sources can write, and what could not be read."""
    trees = {path: ast.parse(text, filename=str(path)) for path, text in sources.items()}
    helpers = audit_helpers(trees)
    names: set[str] = set()
    problems: list[str] = []
    for path, fn in _functions(trees):
        positional, keyword = _params(fn)
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and _callee(call) in helpers):
                continue
            for value in _event_args(call, helpers):
                where = f"{path}:{call.lineno}"
                values: list[ast.expr] | None = [value]
                if isinstance(value, ast.Name):
                    if value.id == "event" and "event" in positional + keyword:
                        continue  # a helper forwarding its argument: checked at its callers
                    values = _loop_values(fn, value.id)
                if values is None:
                    problems.append(f"{where}: event name {ast.unparse(value)} is not a literal")
                    continue
                for item in values:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        names.add(item.value)
                    elif isinstance(item, ast.JoinedStr):
                        template = ast.unparse(item)[2:-1]
                        if template in DYNAMIC_EVENTS:
                            names |= DYNAMIC_EVENTS[template]
                        else:
                            problems.append(f"{where}: f-string event {template!r} not listed")
                    else:
                        problems.append(f"{where}: event name {ast.unparse(item)} unreadable")
    return names, problems


def app_sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in sorted(APP_DIR.rglob("*.py"))}


# --- the catalogue (no database) -----------------------------------------------------------


def test_an_unclassified_event_name_fails_the_catalogue_check() -> None:
    added = APP_DIR / "api" / "example.py"
    sources = app_sources() | {
        added: (
            "async def f(session, t):\n"
            "    await record(session, tenant_id=t, actor_user_id=None,\n"
            "                 event='operator.synthetic_new_event', metadata={})\n"
        )
    }
    names, problems = scan_events(sources)
    assert problems == []
    assert names - AUDIT_EVENTS == {"operator.synthetic_new_event"}


@pytest.mark.parametrize(
    "body",
    [
        # Through a forwarding helper, positionally and by keyword.
        "await audit_sign_in(f, t, u, 'auth.synthetic_new_event', None)",
        "await _audit(session, None, event='source.synthetic_new_event', source_id=s)",
        # From a literal list of steps, as the site crawl writes them.
        "steps = [('site.synthetic_new_event', {}, {})]\n"
        "    for event, before, after in steps:\n"
        "        await record(session, tenant_id=t, actor_user_id=None, event=event, metadata={})",
    ],
)
def test_the_scan_follows_helpers_and_loops(body: str) -> None:
    added = APP_DIR / "api" / "example.py"
    sources = app_sources() | {added: f"async def f(session, t, u, s):\n    {body}\n"}
    names, problems = scan_events(sources)
    assert problems == []
    assert len(names - AUDIT_EVENTS) == 1


@pytest.mark.parametrize(
    "body",
    [
        "await record(session, tenant_id=t, actor_user_id=None, event=name, metadata={})",
        "await record(session, tenant_id=t, actor_user_id=None, event=f'x.{y}', metadata={})",
    ],
)
def test_an_event_name_the_scan_cannot_read_fails(body: str) -> None:
    added = APP_DIR / "api" / "example.py"
    _, problems = scan_events(app_sources() | {added: f"async def f(session, t):\n    {body}\n"})
    assert problems


def test_every_event_the_code_writes_is_classified() -> None:
    names, problems = scan_events(app_sources())
    assert problems == []
    assert names - AUDIT_EVENTS == set(), "classify these in app/audit/events.py"
    # Sanity: the scan sees events through each path (literal, helper, loop, f-string).
    assert {"chat.query", "auth.link_requested", "source.withdrawn", "source.ingested"} <= names
    assert {"tenant_admin.audit_exported", "site.crawled"} <= names


def test_exported_and_operator_only_do_not_overlap() -> None:
    assert not EXPORTED_EVENTS & OPERATOR_ONLY_EVENTS


@pytest.mark.parametrize(
    "event",
    [
        "workspace.prompt_tenant_name_match",
        "model.fallback",
        "chat.query",
        "chat.feedback",
        "operator.tenant_created",
        "operator.workspace_created",
        "operator.workspace_tags_changed",
        "operator.source_downloadable_changed",
    ],
)
def test_operator_only_events_are_not_exported(event: str) -> None:
    assert event in OPERATOR_ONLY_EVENTS and event not in EXPORTED_EVENTS


@pytest.mark.parametrize(
    "event",
    [
        "operator.entitlements_changed",
        "operator.login_policy_changed",
        "operator.sso_source_changed",
    ],
)
def test_operator_sign_in_and_entitlement_changes_are_exported(event: str) -> None:
    """Owner decision, Oct 25, 2026 (Groups B and C question 2): non-secret settings a
    security contact asks about."""
    assert event in EXPORTED_EVENTS and event not in OPERATOR_ONLY_EVENTS


def test_record_refuses_an_unclassified_event() -> None:
    class Session:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, row: Any) -> None:
            self.added.append(row)

    session = Session()
    with pytest.raises(UnclassifiedAuditEvent):
        asyncio.run(
            record(
                session,  # type: ignore[arg-type]
                tenant_id=uuid.uuid4(),
                actor_user_id=None,
                event="operator.synthetic_new_event",
                metadata={},
            )
        )
    assert session.added == []


# --- the export (database) -----------------------------------------------------------------

from tests.test_auth import Auth, auth  # noqa: E402, F401 - fixture
from tests.test_tenant_admin import add_user, admin_of, as_user  # noqa: E402

database = pytest.mark.usefixtures("database")


def export_rows(response: httpx.Response) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    return list(csv.DictReader(io.StringIO(response.text)))


def reset_export_limit(harness: Auth) -> None:
    """A fresh per-admin limiter, as a minute later."""
    harness.app.state.audit_export_limiter = None


async def seed(harness: Auth, tenant_id: uuid.UUID, event: str, at: datetime) -> None:
    await harness.admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event, metadata, created_at) "
        "VALUES ($1, NULL, $2, '{}'::jsonb, $3)",
        tenant_id,
        event,
        at,
    )


@database
async def test_operator_only_events_never_appear_with_every_event_seeded(
    auth: Auth,  # noqa: F811
) -> None:
    tenant, browser = await admin_of(auth)
    now = datetime.now(UTC)
    for event in [*sorted(AUDIT_EVENTS), "operator.synthetic_unclassified", "auth"]:
        await seed(auth, tenant.id, event, now - timedelta(hours=1))
    # Another tenant's exported events stay out too.
    other = await auth.tenant()
    await seed(auth, other.id, "auth.login", now - timedelta(hours=1))

    rows = export_rows(await browser.get("/api/v1/admin/audit-log"))
    exported = [r["event"] for r in rows]
    assert set(exported) == EXPORTED_EVENTS
    assert len(exported) == len(set(exported))  # each seeded once, nothing of the other tenant
    assert not set(exported) & OPERATOR_ONLY_EVENTS
    assert "operator.synthetic_unclassified" not in exported


@database
async def test_the_second_export_within_a_minute_is_refused(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    assert (await browser.get("/api/v1/admin/audit-log")).status_code == 200
    refused = await browser.get("/api/v1/admin/audit-log?since=2026-01-01")
    assert refused.status_code == 429
    assert refused.json()["detail"] == "rate_limited"
    assert 1 <= int(refused.headers["retry-after"]) <= 61
    # The refusal is not an export: one audit event only.
    assert len(await auth.audit("tenant_admin.audit_exported", tenant.id)) == 1
    # The limit is per admin: a second admin of the same tenant may export.
    second = await add_user(auth.admin, tenant, role="tenant_admin")
    assert (await as_user(auth, second.email, tenant.id).get("/api/v1/admin/audit-log")).is_success


@database
async def test_the_export_covers_since_to_until(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    days = [datetime(2026, 9, d, 12, tzinfo=UTC) for d in (1, 10, 20, 30)]
    for at in days:
        await seed(auth, tenant.id, "auth.login", at)
    response = await browser.get("/api/v1/admin/audit-log?since=2026-09-10&until=2026-09-20")
    rows = export_rows(response)
    assert [r["created_at"][:10] for r in rows] == ["2026-09-10", "2026-09-20"]
    assert response.headers["x-audit-export-complete"] == "true"
    assert "x-audit-export-next" not in response.headers
    assert "2026-09-10-2026-09-20" in response.headers["content-disposition"]
    reset_export_limit(auth)
    backwards = await browser.get("/api/v1/admin/audit-log?since=2026-09-20&until=2026-09-10")
    assert (backwards.status_code, backwards.json()["detail"]) == (422, "invalid_period")
    reset_export_limit(auth)
    bad = await browser.get("/api/v1/admin/audit-log?after=not-a-cursor")
    assert (bad.status_code, bad.json()["detail"]) == (422, "invalid_cursor")


@database
async def test_a_period_over_the_row_cap_is_paged_not_truncated(
    auth: Auth,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_routes, "MAX_EXPORT_ROWS", 2)
    tenant, browser = await admin_of(auth)
    start = datetime(2026, 9, 1, 12, tzinfo=UTC)
    for i in range(5):  # two share a timestamp: the cursor breaks the tie by ID
        await seed(auth, tenant.id, "auth.login", start + timedelta(minutes=min(i, 3)))
    seen: list[str] = []
    period = {"since": "2026-09-01", "until": "2026-09-01"}
    cursor: str | None = None
    for _ in range(5):
        reset_export_limit(auth)
        params = period | ({"after": cursor} if cursor else {})
        response = await browser.get("/api/v1/admin/audit-log", params=params)
        rows = export_rows(response)
        seen += [json.dumps(r, sort_keys=True) for r in rows]
        if response.headers["x-audit-export-complete"] == "true":
            break
        assert len(rows) == 2
        cursor = response.headers["x-audit-export-next"]
    assert len(seen) == 5
    events = await auth.audit("tenant_admin.audit_exported", tenant.id)
    assert [e.get("status") for e in events] == ["partial", "partial", "complete"]
