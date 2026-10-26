"""The termination purge (P1b-14; offboarding pack §1.4): one tenant's data, deleted.

``ask-spore tenant purge --slug <slug> --confirm <slug>`` runs it as the schema owner
(``MIGRATIONS_DATABASE_URL``), like the operator grants: the API has no route to it.
In one transaction scoped to the tenant (RLS applies to the owner too, the tables
force it), it

- suspends the tenant and clears its verified domains, so nothing signs in to it and
  its domains can be registered again; the ``tenants`` row stays, because the audit
  events reference it;
- deletes the tenant's history (conversations, messages, citations, feedback), account
  data (users, sign-in links, SSO attempts, MFA challenges, revoked sessions), its
  workspaces and their prompts, its settings, login policy and entitlements, its
  download records, its support grants (P2A-08), its operator notices and the queued or
  finished jobs that name it;
- keeps what the offboarding pack keeps: the audit events (append-only, 12 months),
  and the usage ledger and spend notices (aggregate tokens and cost, billing records);
- removes every answer-cache key under the tenant's prefix (``app.core.cache``), again
  after the commit for anything cached meanwhile;
- writes the certificate of deletion's figures as JSON under ``[files] content_root``
  (``certificates/<number>.json``), with the fields of the offboarding pack's
  certificate template, and records ``tenant.purged`` under the internal tenant with
  the certificate's number and SHA-256 (platform-level audit).

The tenant's Authentik users and SSO source are removed by the operator in Authentik's
admin interface, a documented manual step the certificate lists.

Before deleting anything the purge checks that it knows every table with a
``tenant_id`` column, so a table added later cannot be left out silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import record
from app.core import cache
from app.core.db import OPERATOR_ROLE, set_tenant
from app.tenancy.models import INTERNAL_TENANT_ID

# Deleted, children first (foreign keys).
PURGED_TABLES: Final = (
    "feedback",
    "citations",
    "messages",
    "conversations",
    "downloads",
    "support_grants",
    "revoked_sessions",
    "sign_in_links",
    "sso_attempts",
    "mfa_challenges",
    "workspace_prompts",
    "workspaces",
    "operator_notices",
    "tenant_settings",
    "tenant_login_policy",
    "tenant_entitlements",
    "users",
)
# Kept after termination (offboarding pack §1.4, "What is kept").
KEPT_TABLES: Final = ("audit_events", "usage_ledger", "spend_notices")
# Rows only the internal tenant can have (check constraints); it is never terminated.
INTERNAL_ONLY_TABLES: Final = ("operators", "content_roles")
CERTIFICATES_DIR: Final = "certificates"
METHOD: Final = "Automated termination purge (P1b-14)"
AUDIT_RETENTION_MONTHS: Final = 12
AUTHENTIK_STEP: Final = (
    "Remove the tenant's users and its SSO source in Authentik's admin interface "
    "(users carrying this tenant's ask_spore_tenant attribute; source users under the "
    "path ask-spore/sso), record the number removed on the signed certificate, and "
    "audit the step in the paperwork checklist."
)


class TerminationError(Exception):
    """The purge did not run; ``code`` says why. Nothing was deleted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Termination:
    tenant_id: uuid.UUID
    certificate_number: str
    certificate_path: Path
    counts: dict[str, int]  # rows deleted per table, plus jobs and cache keys

    @property
    def total(self) -> int:
        return sum(self.counts.values())


async def tenant_tables(session: AsyncSession) -> set[str]:
    """Every table in the schema with a ``tenant_id`` column."""
    rows = await session.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
        )
    )
    return {str(r[0]) for r in rows}


def _certificate_number(now: datetime) -> str:
    return f"COD-{now:%Y%m%d}-{secrets.token_hex(4)}"


def _add_months(day: datetime, months: int) -> str:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    # The last day of a shorter month when the day does not exist in it.
    for candidate in (day.day, 30, 29, 28):
        try:
            return day.replace(year=year, month=month, day=candidate).date().isoformat()
        except ValueError:
            continue
    raise AssertionError("unreachable")


def certificate(
    *,
    number: str,
    tenant: dict[str, Any],
    deleted_at: datetime,
    counts: dict[str, int],
    audit_count: int,
    last_audit_at: datetime | None,
    usage_rows: int,
    spend_notice_rows: int,
    sso_source_slug: str | None,
) -> dict[str, Any]:
    """The certificate's figures (offboarding pack §2), counts and dates only."""
    workspaces_and_settings = sum(
        counts.get(t, 0)
        for t in (
            "workspaces",
            "workspace_prompts",
            "tenant_settings",
            "tenant_login_policy",
            "tenant_entitlements",
        )
    )
    return {
        "certificate_number": number,
        "client": {
            "tenant_id": str(tenant["id"]),
            "slug": tenant["slug"],
            "display_name": tenant["display_name"],
        },
        "date_of_deletion": deleted_at.date().isoformat(),
        "deleted_at": deleted_at.isoformat(timespec="seconds"),
        "method": METHOD,
        "deleted": {
            "user_accounts_application": counts.get("users", 0),
            "user_accounts_identity_service": None,  # manual step, see manual_steps
            "conversations": counts.get("conversations", 0),
            "messages": counts.get("messages", 0),
            "citations": counts.get("citations", 0),
            "feedback_entries": counts.get("feedback", 0),
            "download_records": counts.get("downloads", 0),
            "workspaces_and_settings": workspaces_and_settings,
            "sign_in_records": sum(
                counts.get(t, 0)
                for t in ("sign_in_links", "sso_attempts", "mfa_challenges", "revoked_sessions")
            ),
            "operator_notices": counts.get("operator_notices", 0),
            "jobs": counts.get("jobs", 0),
            "cached_answers_removed": counts.get("cache_keys", 0),
            "cached_answers_scope": "All entries under the Client's cache prefix",
        },
        "table_counts": {t: counts.get(t, 0) for t in PURGED_TABLES},
        "retained": {
            "audit_records": {
                "count": audit_count,
                "last_created_on": last_audit_at.date().isoformat() if last_audit_at else None,
                "retained_until": (
                    _add_months(last_audit_at, AUDIT_RETENTION_MONTHS) if last_audit_at else None
                ),
                "note": "Sign-in, administrative, query and download metadata; no question "
                "or answer text. Kept until 12 months after each record was created.",
            },
            "usage_and_spend": {
                "usage_ledger_rows": usage_rows,
                "spend_notices": spend_notice_rows,
                "note": "Aggregate tokens and cost per month and model; no user identifiers.",
            },
            "backups": "Encrypted backups made before the deletion date, until they age out "
            "under the backup retention.",
        },
        "manual_steps": [
            AUTHENTIK_STEP
            + (f" The tenant's SSO source slug was {sso_source_slug}." if sso_source_slug else "")
        ],
        "signature": None,  # signed by the owner on the issued certificate
    }


def _write_certificate(root: Path, number: str, body: dict[str, Any]) -> tuple[Path, str]:
    directory = root / CERTIFICATES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{number}.json"
    data = (json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path, hashlib.sha256(data).hexdigest()


async def _clear_cache(tenant_id: uuid.UUID) -> int:
    return await cache.clear_tenant(tenant_id)


async def terminate_tenant(
    owner_factory: async_sessionmaker[AsyncSession],
    *,
    slug: str,
    confirm: str,
    content_root: Path,
    clear_cache: Callable[[uuid.UUID], Awaitable[int]] = _clear_cache,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Termination:
    """Delete the tenant named by ``slug`` (``confirm`` must repeat it); see the module."""
    if not slug or confirm != slug:
        raise TerminationError("confirmation_mismatch")
    path: Path | None = None
    async with owner_factory() as session, session.begin():
        await set_tenant(session, INTERNAL_TENANT_ID)
        known = set(PURGED_TABLES) | set(KEPT_TABLES) | set(INTERNAL_ONLY_TABLES)
        if await tenant_tables(session) - known:
            raise TerminationError("unknown_tenant_table")
        tenant_id = await _tenant_id(session, slug)
        if tenant_id is None:
            raise TerminationError("no_tenant")
        if tenant_id == INTERNAL_TENANT_ID:
            raise TerminationError("internal_tenant")

        await set_tenant(session, tenant_id)
        tenant = (
            (
                await session.execute(
                    text(
                        "SELECT id, slug, display_name, status, verified_domains "
                        "FROM tenants WHERE id = :id FOR UPDATE"
                    ),
                    {"id": tenant_id},
                )
            )
            .mappings()
            .one()
        )
        sso_source_slug = await session.scalar(
            text("SELECT sso_source_slug FROM tenant_login_policy WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        await session.execute(
            text(
                "UPDATE tenants SET status = 'suspended', verified_domains = '{}'::text[] "
                "WHERE id = :id"
            ),
            {"id": tenant_id},
        )
        counts: dict[str, int] = {}
        for table in PURGED_TABLES:
            result = await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :id"),  # noqa: S608 - constant names
                {"id": tenant_id},
            )
            counts[table] = int(getattr(result, "rowcount", 0) or 0)
        jobs = await session.execute(
            text("DELETE FROM jobs WHERE payload->>'tenant_id' = :id"), {"id": str(tenant_id)}
        )
        counts["jobs"] = int(getattr(jobs, "rowcount", 0) or 0)
        audit_count, last_audit_at = (
            await session.execute(
                text("SELECT count(*), max(created_at) FROM audit_events WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
        ).one()
        usage_rows = await session.scalar(
            text("SELECT count(*) FROM usage_ledger WHERE tenant_id = :id"), {"id": tenant_id}
        )
        spend_notice_rows = await session.scalar(
            text("SELECT count(*) FROM spend_notices WHERE tenant_id = :id"), {"id": tenant_id}
        )
        counts["cache_keys"] = await clear_cache(tenant_id)

        deleted_at = now()
        number = _certificate_number(deleted_at)
        body = certificate(
            number=number,
            tenant=dict(tenant),
            deleted_at=deleted_at,
            counts=counts,
            audit_count=int(audit_count),
            last_audit_at=last_audit_at,
            usage_rows=int(usage_rows or 0),
            spend_notice_rows=int(spend_notice_rows or 0),
            sso_source_slug=sso_source_slug,
        )
        path, digest = _write_certificate(content_root, number, body)
        try:
            await set_tenant(session, INTERNAL_TENANT_ID)
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=None,
                event="tenant.purged",
                metadata={
                    "before": {
                        "slug": tenant["slug"],
                        "status": tenant["status"],
                        "verified_domains": list(tenant["verified_domains"]),
                    },
                    "after": {"status": "suspended", "verified_domains": []},
                    "count": sum(counts.values()),
                    "certificate": number,
                    "certificate_sha256": digest,
                    "method": "cli",
                },
            )
            await session.flush()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    # Anything cached between the first clear and the commit goes too.
    counts["cache_keys"] += await clear_cache(tenant_id)
    return Termination(tenant_id, number, path, counts)


async def _tenant_id(session: AsyncSession, slug: str) -> uuid.UUID | None:
    """The tenant's ID by slug. ``tenants`` has forced RLS (a session sees only the tenant
    it is scoped to), so the lookup runs as ``askspore_operator``, whose console policy
    reads every tenant (revision 0006), and switches back to the owner afterwards."""
    await session.execute(text(f"SET LOCAL ROLE {OPERATOR_ROLE}"))
    try:
        found = await session.scalar(
            text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug}
        )
    finally:
        await session.execute(text("RESET ROLE"))
    return found if isinstance(found, uuid.UUID) else None
