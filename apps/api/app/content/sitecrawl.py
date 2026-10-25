"""The ``crawl_site`` job (P1b-04): one crawl of one approved site, kept in step with the
source register.

1. Refuse a site that is not approved, or whose approver no longer holds
   ``content_reviewer`` (their approval covers the pages), and a start URL that does not
   resolve to a public address (checked again for every request, redirects included).
2. Record the site's allow decision from robots.txt and the TDM reservation
   (``app.content.crawler``). A site that now disallows us or reserves its rights has
   every live page withdrawn.
3. Walk the site within its scope rules and page budget, at the per-host rate limit.
   Each page URL is a ``site_pages`` row:

   - a new page, or a page whose rendered Markdown changed (by SHA-256), becomes an
     approved register row (canonical link: the page URL; publication date from
     explicit page metadata only), staged under ``content_root`` with its raw HTML
     snapshot (``snapshots/<sha256>.html``) and fetch date, and is queued for
     ingestion; a changed page names the version it replaces (``supersedes_id``), so
     the A1 supersession path withdraws the old one once the new one is ingested;
   - an unchanged page only has its fetch date updated;
   - a blocked page (noai or noindex, no readable content, a special category not
     whitelisted, a duplicate of another source, taken down) is listed with its reason;
4. Revisit the live pages the walk did not reach: a page that is gone (HTTP 404 or 410)
   or moved is ``removed``; one now out of scope or disallowed is ``blocked``.
5. Withdraw (``withdraw_source`` jobs) the register rows of this site that are no longer
   any live page's current version, unless a newer version still waits to replace them.
6. Record the crawl on the site (date, outcome, live page count, next due date), audited.

A site a reviewer withdraws while it is being crawled (P1c-14) stops the crawl at its
next page: every page is checked against the site's status, and a page is admitted
only under a share lock on the site row, so it is either admitted before the
withdrawal (which then blocks and withdraws it) or not at all. A reinstated site
(P2A-12 a) is crawled again only once a reviewer approves it afresh; its pages released
at reinstatement (``removed``, ``reinstated``) are admitted as new rows, and its pages
under a takedown stay blocked by the reason check and the takedown check below.

Log lines and audit events carry identifiers, codes and counts only, never page text,
titles or URLs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import Change, record
from app.content.crawler import HostLimiter, Scope, SiteCrawler, Visit
from app.content.fetch import (
    Connector,
    FetchError,
    Resolver,
    http_client,
    require_public_url,
    resolve_host,
)
from app.content.jobs import enqueue
from app.content.models import Site, SitePage, Source
from app.content.roles import REVIEWER, roles_of
from app.content.sites import next_crawl
from app.content.special import special_category, whitelisted
from app.content.store import stage, store_snapshot
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID

ALLOW_DECISION: Final = {
    "ok": "allowed",
    "robots_disallowed": "robots_disallowed",
    "tdm_reserved": "tdm_reserved",
}
# The withdrawal reason kept on the register row, by the page's state reason.
WITHDRAWAL_REASONS: Final = {
    "http_404": "page removed from the site (HTTP 404)",
    "http_410": "page removed from the site (HTTP 410)",
    "moved": "page moved to another address",
    "robots": "robots.txt now disallows the page",
    "out_of_scope": "page outside the site's scope rules",
    "noai_or_noindex": "page now marked noai or noindex",
    "special_category": "page matches a special-category pattern",
    "no_content": "page has no readable content",
    "robots_disallowed": "robots.txt disallows the site",
    "tdm_reserved": "the site reserves text-and-data-mining rights",
}
EARLIER_VERSION = "an earlier version of a crawled page"


@dataclass(frozen=True)
class CrawlResult:
    site_id: UUID
    status: str  # ok, robots_disallowed, tdm_reserved, unreachable, refused
    error_code: str | None = None
    counts: Counter[str] = field(default_factory=Counter)


class _SiteWithdrawn(Exception):
    """The site stopped being approved during the crawl (a reviewer withdrew it)."""


async def _approved(session: AsyncSession, site_id: UUID, *, lock: bool = False) -> bool:
    query = select(Site.status).where(Site.id == site_id)
    if lock:
        query = query.with_for_update(read=True)
    return await session.scalar(query) == "approved"


@dataclass(frozen=True)
class _Known:
    state: str
    reason: str | None
    source_id: UUID | None
    source_status: str | None
    source_sha: str | None


async def _known(factory: async_sessionmaker[AsyncSession], site_id: UUID) -> dict[str, _Known]:
    async with factory() as session:
        rows = await session.execute(
            select(
                SitePage.url,
                SitePage.state,
                SitePage.reason,
                SitePage.source_id,
                Source.status,
                Source.file_sha256,
            )
            .outerjoin(Source, Source.id == SitePage.source_id)
            .where(SitePage.site_id == site_id)
        )
        return {
            r.url: _Known(r.state, r.reason, r.source_id, r.status, r.file_sha256) for r in rows
        }


async def _set_page(
    session: AsyncSession,
    site_id: UUID,
    url: str,
    state: str,
    *,
    reason: str | None = None,
    category: str | None = None,
    source_id: UUID | None = None,
    published_on: date | None = None,
    fetched: bool = True,
) -> None:
    values: dict[str, object] = {
        "state": state,
        "reason": reason,
        "special_category": category,
        "last_seen_at": func.now(),
    }
    if source_id is not None:
        values["source_id"] = source_id
    if state == "live":
        values["published_on"] = published_on
    if fetched:
        values["fetched_at"] = func.now()
    await session.execute(
        insert(SitePage)
        .values(site_id=site_id, url=url, **values)
        .on_conflict_do_update(index_elements=["site_id", "url"], set_=values)
    )


class _Crawl:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        site: Site,
        known: dict[str, _Known],
        content_root: Path,
    ) -> None:
        self.factory = factory
        self.site = site
        self.known = known
        self.content_root = content_root
        self.counts: Counter[str] = Counter()

    async def apply(self, visit: Visit) -> None:
        async with self.factory() as session:
            if not await _approved(session, self.site.id):
                raise _SiteWithdrawn
        known = self.known.get(visit.url)
        if known is not None and known.reason in ("withdrawn", "taken_down"):
            return  # a reviewer withdrew the page: it stays out, whatever the site does
        if visit.kind == "page":
            await self._page(visit, known)
        elif visit.kind == "blocked":
            async with self.factory() as session, session.begin():
                await _set_page(
                    session,
                    self.site.id,
                    visit.url,
                    "blocked",
                    reason=visit.reason,
                    category=visit.special_category,
                )
            self.counts["blocked"] += 1
        elif visit.kind == "missing" and known is not None and known.state != "removed":
            async with self.factory() as session, session.begin():
                await _set_page(session, self.site.id, visit.url, "removed", reason=visit.reason)
            self.counts["removed"] += 1
        # An error (timeout, server error) changes nothing: the page stays as it was.

    async def _page(self, visit: Visit, known: _Known | None) -> None:
        content = (visit.markdown + "\n").encode()
        sha = hashlib.sha256(content).hexdigest()
        supersedes: UUID | None = None
        if known is not None and known.state == "live":
            if known.source_status == "withdrawn":
                # A reviewer withdrew the page's register row: it stays out.
                await self._block(visit.url, "withdrawn")
                return
            held = await self._held(known.source_id)
            if known.source_sha == sha or known.source_status in ("proposed", "approved") or held:
                # Unchanged, in flight, or under a takedown or pending withdrawal: no new
                # version may slip past the reviewer's decision.
                async with self.factory() as session, session.begin():
                    await session.execute(
                        update(SitePage)
                        .where(SitePage.site_id == self.site.id, SitePage.url == visit.url)
                        .values(
                            last_seen_at=func.now(),
                            fetched_at=func.now(),
                            published_on=visit.published_on,
                        )
                    )
                self.counts["unchanged"] += 1
                return
            supersedes = known.source_id

        async with tenant_session(self.factory, INTERNAL_TENANT_ID) as session:
            if not await _approved(session, self.site.id, lock=True):
                raise _SiteWithdrawn
            same = (
                await session.execute(
                    select(Source.status, Source.takedown_reference).where(
                        Source.file_sha256 == sha
                    )
                )
            ).all()
            taken_down_here = await session.scalar(
                select(func.count())
                .select_from(Source)
                .where(
                    Source.site_id == self.site.id,
                    Source.canonical_url == visit.url,
                    Source.takedown_reference.is_not(None),
                )
            )
            if taken_down_here or any(
                r.status == "withdrawn" and r.takedown_reference for r in same
            ):
                reason: str | None = "taken_down"
            elif any(r.status != "withdrawn" for r in same):
                reason = "duplicate_content"
            else:
                reason = None
            if reason is not None:
                await _set_page(session, self.site.id, visit.url, "blocked", reason=reason)
                self.counts["blocked"] += 1
                return
            source_id = await self._admit(session, visit, content, sha, supersedes)
            await _set_page(
                session,
                self.site.id,
                visit.url,
                "live",
                source_id=source_id,
                published_on=visit.published_on,
            )
        self.counts["changed" if supersedes else "new"] += 1

    async def _held(self, source_id: UUID | None) -> bool:
        """A takedown is recorded, or a withdrawal requested, on the page's current row."""
        if source_id is None:
            return False
        async with self.factory() as session:
            row = (
                await session.execute(
                    select(Source.takedown_reference, Source.withdrawal_reason).where(
                        Source.id == source_id
                    )
                )
            ).first()
        return row is not None and bool(row.takedown_reference or row.withdrawal_reason)

    async def _block(self, url: str, reason: str) -> None:
        async with self.factory() as session, session.begin():
            await _set_page(session, self.site.id, url, "blocked", reason=reason)
        self.counts["blocked"] += 1

    async def _admit(
        self,
        session: AsyncSession,
        visit: Visit,
        content: bytes,
        sha: str,
        supersedes: UUID | None,
    ) -> UUID:
        """The page as an approved register row, in the site approver's name, queued."""
        site = self.site
        stage(self.content_root, sha, "markdown", content)
        snapshot = store_snapshot(self.content_root, visit.raw)
        source_id = await session.scalar(
            insert(Source)
            .values(
                type="markdown",
                title=(visit.title or visit.url)[:500],
                publisher=site.publisher,
                published_on=visit.published_on,
                canonical_url=visit.url,
                licence_basis=site.licence_basis,
                tags=list(site.tags),
                status="approved",
                file_sha256=sha,
                proposed_by=site.proposed_by,
                approved_by=site.approved_by,
                approved_at=func.now(),
                supersedes_id=supersedes,
                site_id=site.id,
                snapshot_path=snapshot,
                fetched_at=func.now(),
            )
            .returning(Source.id)
        )
        if source_id is None:
            raise AssertionError("the insert returns the new row's ID")
        await enqueue(session, "ingest_source", {"source_id": str(source_id)}, created_by=None)
        steps: list[tuple[str, Change, Change]] = [
            ("source.proposed", {}, {"status": "proposed"}),
            ("source.approved", {"status": "proposed"}, {"status": "approved"}),
        ]
        for event, before, after in steps:
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=None,
                event=event,
                metadata={
                    "source_id": str(source_id),
                    "site_id": str(site.id),
                    "before": before,
                    "after": after,
                    "method": "site_crawl",
                },
            )
        new_id: UUID = source_id
        return new_id

    async def block_live(self, reason: str) -> None:
        """Every page live now, those admitted earlier in this crawl included."""
        async with self.factory() as session:
            urls = (
                await session.scalars(
                    select(SitePage.url).where(
                        SitePage.site_id == self.site.id, SitePage.state == "live"
                    )
                )
            ).all()
        for url in urls:
            await self._block(url, reason)

    async def sweep(self) -> None:
        """Withdraw this site's register rows that no live page holds any more."""
        async with tenant_session(self.factory, INTERNAL_TENANT_ID) as session:
            pages = (
                await session.execute(
                    select(SitePage.source_id, SitePage.state, SitePage.reason).where(
                        SitePage.site_id == self.site.id, SitePage.source_id.is_not(None)
                    )
                )
            ).all()
            live = {p.source_id for p in pages if p.state == "live"}
            reasons = {p.source_id: p.reason for p in pages if p.state != "live"}
            rows = (
                await session.execute(
                    select(Source.id, Source.status, Source.supersedes_id)
                    .where(Source.site_id == self.site.id)
                    .with_for_update()
                )
            ).all()
            # A version a newer one will replace stays until that one is ingested.
            pending = {r.supersedes_id for r in rows if r.status != "withdrawn"}
            for row in rows:
                if row.status not in ("ingested", "failed") or row.id in live | pending:
                    continue
                code = reasons.get(row.id)
                reason = WITHDRAWAL_REASONS.get(code or "", EARLIER_VERSION)
                await session.execute(
                    update(Source)
                    .where(Source.id == row.id)
                    .values(withdrawal_reason=reason, updated_at=func.now())
                )
                await enqueue(
                    session, "withdraw_source", {"source_id": str(row.id)}, created_by=None
                )
                await record(
                    session,
                    tenant_id=INTERNAL_TENANT_ID,
                    actor_user_id=None,
                    event="source.withdrawal_requested",
                    metadata={
                        "source_id": str(row.id),
                        "site_id": str(self.site.id),
                        "before": {"status": row.status},
                        "after": {"status": row.status},
                        "method": "site_crawl",
                    },
                )
                self.counts["withdrawn"] += 1


async def _finish(
    factory: async_sessionmaker[AsyncSession],
    site: Site,
    status: str,
    *,
    counts: Counter[str],
    decision: str | None,
) -> None:
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        # A site withdrawn meanwhile keeps no next crawl (P1c-14).
        approved = await _approved(session, site.id, lock=True)
        live = await session.scalar(
            select(func.count())
            .select_from(SitePage)
            .where(SitePage.site_id == site.id, SitePage.state == "live")
        )
        values: dict[str, object] = {
            "last_crawl_at": func.now(),
            "last_crawl_status": status,
            "page_count": live or 0,
            "next_crawl_at": next_crawl(site.schedule, datetime.now(UTC)) if approved else None,
            "updated_at": func.now(),
        }
        if decision is not None:
            values |= {"allow_decision": decision, "allow_checked_at": func.now()}
        await session.execute(update(Site).where(Site.id == site.id).values(**values))
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=None,
            event="site.crawled",
            metadata={
                "site_id": str(site.id),
                "outcome": status,
                "count": live or 0,
                "status": decision,
            },
        )


async def crawl_site(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    *,
    content_root: Path,
    limiter: HostLimiter,
    resolve: Resolver = resolve_host,
    connect: Connector | None = None,
) -> CrawlResult:
    """Run one crawl of ``site_id`` (see the module docstring). Every request, redirects
    included, goes through ``http_client(resolve, connect)``: public addresses only,
    connected to the address that was checked (P1b-18)."""
    async with factory() as session:
        site = await session.scalar(select(Site).where(Site.id == site_id))
    if site is None:
        return CrawlResult(site_id, "refused", "no_site")
    if site.status != "approved" or site.approved_by is None:
        return CrawlResult(site_id, "refused", "site_not_approved")
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        if REVIEWER not in await roles_of(session, site.approved_by):
            return CrawlResult(site_id, "refused", "approver_lacks_role")
    try:
        await require_public_url(site.start_url, resolve)
    except FetchError as exc:
        await _finish(factory, site, exc.code, counts=Counter(), decision=None)
        return CrawlResult(site_id, "unreachable", exc.code)

    async with http_client(resolve, connect) as http:
        try:
            return await _crawl(factory, site, http, limiter, content_root)
        except _SiteWithdrawn:
            return CrawlResult(site_id, "refused", "site_not_approved")


async def _crawl(
    factory: async_sessionmaker[AsyncSession],
    site: Site,
    http: httpx.AsyncClient,
    limiter: HostLimiter,
    content_root: Path,
) -> CrawlResult:
    site_id = site.id
    allow = list(site.special_category_allow)

    def special(url: str, title: str) -> str | None:
        return None if whitelisted(url, allow) else special_category(url, title)

    crawler = SiteCrawler(
        http,
        site.start_url,
        max_pages=site.max_pages,
        scope=Scope(tuple(site.allow_patterns), tuple(site.deny_patterns)),
        special=special,
        limiter=limiter,
    )
    known = await _known(factory, site_id)
    crawl = _Crawl(factory, site, known, content_root)
    status: str = await crawler.check()
    if status == "unreachable":
        await _finish(factory, site, "unreachable", counts=crawl.counts, decision=None)
        return CrawlResult(site_id, "unreachable", "site_unreachable", crawl.counts)
    if status == "ok":
        seen: set[str] = set()
        async for visit in crawler.walk():
            seen.add(visit.url)
            if visit.reason != "tdm_reserved":
                await crawl.apply(visit)
        status = crawler.status
        if status == "ok":
            for url, page in known.items():
                if page.state == "live" and url not in seen:
                    await crawl.apply(await crawler.revisit(url))
    if status in ("robots_disallowed", "tdm_reserved"):
        await crawl.block_live(status)
    await crawl.sweep()
    await _finish(factory, site, status, counts=crawl.counts, decision=ALLOW_DECISION[status])
    return CrawlResult(site_id, status, None, crawl.counts)
