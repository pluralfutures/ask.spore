"""Audit event writer. Metadata only: never query, answer, prompt or chunk text.

Metadata keys are allow-listed, as for ``app.core.logging.log``; values are scalars
or lists of short strings (IDs). Operator changes (P1a-03) also carry ``before`` and
``after``: one-level mappings whose keys are allow-listed setting names
(``CHANGE_FIELDS``) and whose values follow the same rules. The table is append-only
(revision 0001).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AUDIT_EVENTS
from app.audit.models import AuditEvent

AUDIT_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "conversation_id",
        "message_id",
        "mode",
        "outcome",
        "status",
        "error_code",
        "model",
        "prompt",
        "cache_hit",
        "retrieved_chunk_count",
        "context_chunk_count",
        "cited_chunk_ids",
        "cited_source_ids",
        "corpus_version",
        "tokens_in",
        "tokens_out",
        "latency_ms",
        "rating",
        # Sign-in (P1a-02): how the user authenticated; with a second factor (P1b-08).
        "method",
        "mfa",
        # Operator console (P1a-03): who acted, what changed, and the client's
        # acceptance of external models when they are enabled.
        "operator_id",
        "before",
        "after",
        "acceptance_reference",
        "acceptance_date",
        # Workspaces (P1a-04 to P1a-07): which workspace and prompt version, the
        # conversation's reasoning setting, and which kinds of tenant name matched.
        "workspace_id",
        "version",
        "instructions_version",
        "reasoning",
        "match_kinds",
        # Model choice (P1a-10): the model a new conversation asked for before the
        # external spend cap made it fall back.
        "requested_model",
        # Tenant admin (P1a-13): how many conversations a shorter retention expired.
        "count",
        # Downloads (P1a-14): which register source was downloaded or toggled.
        "source_id",
        # Source register (P1b-01): the acting user's content roles, and whether a
        # reviewer approves their own proposal (allowed and audited, owner decision).
        "roles",
        "self_approval",
        # Re-ingestion choice (owner decision 4, Oct 22, 2026): the source an approved
        # proposal replaces, or the reviewer's "keep both"; and whether a withdrawal on
        # licence grounds blanked the stored excerpts (decision 5).
        "replaces",
        "keep_both",
        "excerpts_blanked",
        # Crawl management (P1b-04): which registered site.
        "site_id",
        # Platform mail (P1b-11): which template went to the user (with "version"), the
        # job that sent it, and the provider. Never the address, subject or body.
        "template",
        "job_id",
        "provider",
        # Termination purge (P1b-14): the certificate of deletion's number and the
        # SHA-256 of its JSON file; the per-table counts are in the file.
        "certificate",
        "certificate_sha256",
        # Failover (P1b-17): which backup answered ("eu" or "external"), or none.
        "failover",
        # Support access (P2A-08): which grant, its scope and length. Never its note.
        "grant_id",
        "scope",
        "duration_minutes",
    }
)
# Keys allowed inside "before" and "after": tenant, entitlement and user settings.
CHANGE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "slug",
        "display_name",
        "verified_domains",
        "status",
        "answer_modes",
        "enabled_models",
        "external_models_enabled",
        "external_spend_cap_cents",
        "sign_in_links_enabled",
        # Login policy (P1b-06, P1b-07): non-secret fields only.
        "sso_source_kind",
        "sso_source_slug",
        "sso_config_sha256",
        "jit_provisioning_enabled",
        "admin_mfa_required",
        "external_acceptance_reference",
        "external_acceptance_date",
        "user_id",
        "role",
        # Workspaces (P1a-04): the package builder's settings.
        "workspace_id",
        "name",
        "tag_ids",
        "default_mode",
        "default_model",
        "default_reasoning",
        # Tenant admin pages (P1a-13): chat-history retention.
        "retention_days",
        # Operator console (P1a-14): a source's download switch.
        "source_id",
        "downloadable",
        # Takedown queue (P1b-03): the request's reference and due date.
        "takedown_reference",
        "takedown_due_on",
        "takedown_licence_grounds",
        # Crawl management (P1b-04): a site's scope rules, schedule, page budget and the
        # reviewer's special-category whitelist (path patterns).
        "allow_patterns",
        "deny_patterns",
        "schedule",
        "max_pages",
        "special_category_allow",
    }
)
CHANGE_KEYS: Final = frozenset({"before", "after"})
MAX_VALUE_LENGTH: Final = 128
MAX_LIST_LENGTH: Final = 64

Scalar = str | int | float | bool | None
Change = dict[str, Scalar | list[str]]
AuditValue = Scalar | list[str] | Change


class ForbiddenAuditField(ValueError):
    """An audit event carried a key or value shape that is not allowed."""


class UnclassifiedAuditEvent(ValueError):
    """An event name that ``app.audit.events`` does not classify (P2A-07)."""


def _check_value(key: str, value: object) -> None:
    values = value if isinstance(value, list) else [value]
    if len(values) > MAX_LIST_LENGTH:
        raise ForbiddenAuditField(f"audit metadata '{key}' list is too long")
    for item in values:
        if not isinstance(item, str | int | float | bool | None):
            raise ForbiddenAuditField(f"audit metadata '{key}' must be scalar or list[str]")
        if isinstance(item, str) and len(item) > MAX_VALUE_LENGTH:
            raise ForbiddenAuditField(f"audit metadata '{key}' value is too long")


def _check(metadata: dict[str, AuditValue]) -> None:
    forbidden = sorted(set(metadata) - AUDIT_METADATA_KEYS)
    if forbidden:
        raise ForbiddenAuditField(f"audit metadata key(s) not allow-listed: {', '.join(forbidden)}")
    for key, value in metadata.items():
        if key in CHANGE_KEYS:
            if not isinstance(value, dict):
                raise ForbiddenAuditField(f"audit metadata '{key}' must be a mapping")
            fields = sorted(set(value) - CHANGE_FIELDS)
            if fields:
                raise ForbiddenAuditField(
                    f"audit metadata '{key}' field(s) not allow-listed: {', '.join(fields)}"
                )
            for field, item in value.items():
                _check_value(f"{key}.{field}", item)
        elif isinstance(value, dict):
            raise ForbiddenAuditField(f"audit metadata '{key}' must be scalar or list[str]")
        else:
            _check_value(key, value)


async def record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    event: str,
    metadata: dict[str, AuditValue],
) -> None:
    """Add one audit row to the session's (tenant-scoped) transaction."""
    if event not in AUDIT_EVENTS:
        raise UnclassifiedAuditEvent(f"audit event {event!r} is not in app.audit.events")
    _check(metadata)
    session.add(
        AuditEvent(
            tenant_id=tenant_id, actor_user_id=actor_user_id, event=event, metadata_=metadata
        )
    )
