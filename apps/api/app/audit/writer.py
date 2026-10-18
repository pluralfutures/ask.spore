"""Audit event writer. Metadata only: never query, answer, prompt or chunk text.

Metadata keys are allow-listed, as for ``app.core.logging.log``; values are scalars
or lists of short strings (IDs). The table is append-only (revision 0001).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
    }
)
MAX_VALUE_LENGTH: Final = 128

AuditValue = str | int | float | bool | None | list[str]


class ForbiddenAuditField(ValueError):
    """An audit event carried a key or value shape that is not allowed."""


def _check(metadata: dict[str, AuditValue]) -> None:
    forbidden = sorted(set(metadata) - AUDIT_METADATA_KEYS)
    if forbidden:
        raise ForbiddenAuditField(f"audit metadata key(s) not allow-listed: {', '.join(forbidden)}")
    for key, value in metadata.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str | int | float | bool | None):
                raise ForbiddenAuditField(f"audit metadata '{key}' must be scalar or list[str]")
            if isinstance(item, str) and len(item) > MAX_VALUE_LENGTH:
                raise ForbiddenAuditField(f"audit metadata '{key}' value is too long")


async def record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    event: str,
    metadata: dict[str, AuditValue],
) -> None:
    """Add one audit row to the session's (tenant-scoped) transaction."""
    _check(metadata)
    session.add(
        AuditEvent(
            tenant_id=tenant_id, actor_user_id=actor_user_id, event=event, metadata_=metadata
        )
    )
