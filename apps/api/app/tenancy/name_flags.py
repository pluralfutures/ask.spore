"""Tenant-name flag on saved workspace prompts (P1a-07).

Tenant-authored instructions may name the tenant or its staff: the compliance guide
(addendum of Oct 18, 2026) permits it as a tenant-authored exception to the "no
tenant identifiers in prompts" control, on condition that every such save is flagged
to the operator. ``match_kinds`` checks a text against the tenant's display name,
verified domains and its users' names and emails, case-insensitively and as whole
words. The caller writes an operator notice and an audit event naming only which
kinds matched; the matched text is never stored, logged or returned, and nothing
reaches the tenant user.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.models import Tenant, User

MatchKind = str  # one of KINDS
KINDS = ("tenant_name", "domain", "user_name", "user_email")
MIN_TERM_CHARS = 3  # shorter names ("Al", "X") would flag ordinary words


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    """One regex for whole-word matches of any term; whitespace inside a term is flexible."""
    cleaned = sorted(
        {_normalise(t).strip() for t in terms if len(t.strip()) >= MIN_TERM_CHARS},
        key=len,
        reverse=True,
    )
    if not cleaned:
        return None
    parts = [r"\s+".join(re.escape(word) for word in term.split()) for term in cleaned]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")


def match_kinds(text: str, terms: Mapping[MatchKind, Iterable[str]]) -> list[MatchKind]:
    """Which kinds of tenant term occur in ``text`` as whole words, in ``KINDS`` order."""
    haystack = _normalise(text)
    found = []
    for kind in KINDS:
        pattern = _pattern(terms.get(kind, ()))
        if pattern is not None and pattern.search(haystack):
            found.append(kind)
    return found


async def tenant_terms(session: AsyncSession) -> dict[MatchKind, list[str]]:
    """The session's tenant's names, domains and users (RLS: this tenant only)."""
    tenant = (await session.execute(select(Tenant.display_name, Tenant.verified_domains))).one()
    users = (await session.execute(select(User.display_name, User.email))).all()
    return {
        "tenant_name": [tenant.display_name],
        "domain": list(tenant.verified_domains),
        "user_name": [u.display_name for u in users],
        "user_email": [u.email for u in users],
    }
