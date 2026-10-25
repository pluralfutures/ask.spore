"""Sites (P1b-04): registered websites, their crawl settings and their review.

A content editor registers a site: start URL, the metadata its pages get (name,
publisher, licence basis, tags), scope rules (shell-style path patterns to allow and
deny, e.g. ``/reports/*``), schedule (none, weekly, monthly) and page budget. A content
reviewer approves it (or rejects it, with a note); approval queues its first
``crawl_site`` job (``app.content.sitecrawl``). The reviewer's approval of the site
covers its pages: each crawl records every new or changed page as an approved register
row in the reviewer's name, audited with ``method: site_crawl`` (findings A2).

After approval, the scope, schedule and page budget, and the whitelist of paths exempt
from the special-category skip, are the reviewer's to change; the tags and licence are
fixed (register a new site to change them). Any content role may ask for a crawl now.
Every change is audited under the internal tenant with before and after.

``schedule_due_crawls`` (called by the worker between jobs) queues the crawls that are
due. The start URL must be a public http(s) URL (``app.content.fetch.require_public_url``).

P1c-14: a reviewer may withdraw a whole site (``withdraw_site``): the site is retired
(``withdrawn``, never crawled again), every page is blocked and every page's register
row is withdrawn by the per-page ``withdraw_source`` job. A reviewer may also restore a
withdrawn crawled page (``restore_page``), so the next crawl takes it again. Both are
audited.

P2A-12 (a): a reviewer may reinstate a withdrawn site (``reinstate_site``): it goes back
to ``proposed`` with a required note and needs a fresh approval before anything is
crawled; its start URL is unchanged. Its withdrawn register rows stay withdrawn; every
page held out by a takedown stays blocked, a page a reviewer withdrew on its own stays
out, and the pages the site withdrawal held out are released, so the first crawl after
the approval admits them as new rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditValue, Change, record
from app.content.crawler import normalise
from app.content.fetch import Resolver, require_public_url, resolve_host
from app.content.jobs import enqueue
from app.content.models import MAX_SITE_PAGES, SITE_SCHEDULES, Dataset, Site, SitePage, Source
from app.content.register import MAX_NOTE_LENGTH, RegisterError
from app.content.roles import EDITOR, REVIEWER, require, roles_of
from app.content.tags import TagConfig
from app.core.db import tenant_session
from app.tenancy.models import INTERNAL_TENANT_ID

SCHEDULE_DAYS: Final[Mapping[str, int]] = {"weekly": 7, "monthly": 30}
# Page reasons (``site_pages.reason``, P1c-14): the whole site was withdrawn; a reviewer
# restored a page they had withdrawn (the next crawl takes it again).
SITE_WITHDRAWN: Final = "site_withdrawn"
RESTORED: Final = "restored"
# P2A-12 (a): a page released when its site was reinstated; a page of a reinstated site
# kept out because a takedown was recorded on a version of it.
REINSTATED: Final = "reinstated"
TAKEN_DOWN: Final = "taken_down"
# A reinstatement releases only the pages the site withdrawal held out; a page a reviewer
# withdrew on its own stays out (owner decision, Oct 25, 2026; "Restore page" brings it
# back one by one after the fresh approval).
_RELEASED_ON_REINSTATEMENT: Final = (SITE_WITHDRAWN,)
_WITHDRAWN_PAGE_REASONS: Final = (SITE_WITHDRAWN, "withdrawn", TAKEN_DOWN)
MAX_PATTERNS: Final = 50
MAX_PATTERN_LENGTH: Final = 128  # an audit value's limit
MAX_FIELD_LENGTH: Final = 300


@dataclass(frozen=True)
class SiteSpec:
    """What an editor registers."""

    start_url: str
    name: str
    publisher: str
    licence_basis: str
    tags: tuple[str, ...]
    allow_patterns: tuple[str, ...] = ()
    deny_patterns: tuple[str, ...] = ()
    schedule: str = "none"
    max_pages: int = 50


@dataclass(frozen=True)
class SiteSettings:
    """What a reviewer may change on a registered site."""

    allow_patterns: tuple[str, ...]
    deny_patterns: tuple[str, ...]
    schedule: str
    max_pages: int


def next_crawl(schedule: str, after: datetime) -> datetime | None:
    days = SCHEDULE_DAYS.get(schedule)
    return None if days is None else after + timedelta(days=days)


def check_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    """Path patterns: each starts with ``/``, short, printable; at most 50."""
    cleaned = tuple(dict.fromkeys(p.strip() for p in patterns if p.strip()))
    if len(cleaned) > MAX_PATTERNS:
        raise RegisterError("too_many_patterns")
    for pattern in cleaned:
        if (
            not pattern.startswith("/")
            or len(pattern) > MAX_PATTERN_LENGTH
            or not pattern.isprintable()
            or " " in pattern
        ):
            raise RegisterError("bad_pattern")
    return cleaned


def _check_settings(schedule: str, max_pages: int) -> None:
    if schedule not in SITE_SCHEDULES:
        raise RegisterError("bad_schedule")
    if not 1 <= max_pages <= MAX_SITE_PAGES:
        raise RegisterError("bad_max_pages")


def _text(value: str, code: str) -> str:
    value = value.strip()
    if not value or len(value) > MAX_FIELD_LENGTH:
        raise RegisterError(code)
    return value


def _note(note: str | None, *, required: bool) -> str | None:
    note = (note or "").strip() or None
    if required and note is None:
        raise RegisterError("note_required")
    if note is not None and len(note) > MAX_NOTE_LENGTH:
        raise RegisterError("note_too_long")
    return note


def _settings(site: Site) -> Change:
    return {
        "allow_patterns": list(site.allow_patterns),
        "deny_patterns": list(site.deny_patterns),
        "schedule": site.schedule,
        "max_pages": site.max_pages,
    }


async def _audit(
    session: AsyncSession,
    actor: UUID | None,
    event: str,
    site_id: UUID,
    before: Change,
    after: Change,
    **extra: AuditValue,
) -> None:
    await record(
        session,
        tenant_id=INTERNAL_TENANT_ID,
        actor_user_id=actor,
        event=event,
        metadata={"site_id": str(site_id), "before": before, "after": after, **extra},
    )


async def _locked(session: AsyncSession, site_id: UUID) -> Site:
    site = await session.scalar(select(Site).where(Site.id == site_id).with_for_update())
    if site is None:
        raise RegisterError("no_site")
    return site


async def register_site(
    factory: async_sessionmaker[AsyncSession],
    tags_config: Mapping[str, TagConfig],
    spec: SiteSpec,
    *,
    proposer_id: UUID | None,
    resolve: Resolver = resolve_host,
) -> tuple[UUID, bool]:
    """Record a proposed site; returns its ID and whether it is new (a site with the
    same start URL is returned as it is). ``proposer_id`` must hold ``content_editor``;
    None is the operator's shell (the manifest CLI). Raises RegisterError, or
    FetchError for a start URL that is not public."""
    tags = tuple(dict.fromkeys(spec.tags))
    if not tags:
        raise RegisterError("no_tag")
    if any(tag not in tags_config for tag in tags):
        raise RegisterError("unknown_tag")
    name = _text(spec.name, "missing_metadata")
    publisher = _text(spec.publisher, "missing_metadata")
    licence = _text(spec.licence_basis, "missing_metadata")
    allow, deny = check_patterns(spec.allow_patterns), check_patterns(spec.deny_patterns)
    _check_settings(spec.schedule, spec.max_pages)
    start_url = normalise(spec.start_url.strip())
    if len(start_url) > MAX_FIELD_LENGTH:
        raise RegisterError("bad_url")
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        if proposer_id is not None:
            await require(session, proposer_id, EDITOR)
        await require_public_url(start_url, resolve)
        synced = set(await session.scalars(select(Dataset.tag).where(Dataset.tag.in_(tags))))
        if set(tags) - synced:
            raise RegisterError("no_dataset")
        site_id = await session.scalar(
            insert(Site)
            .values(
                start_url=start_url,
                host=urlsplit(start_url).hostname or "",
                name=name,
                publisher=publisher,
                licence_basis=licence,
                tags=list(tags),
                allow_patterns=list(allow),
                deny_patterns=list(deny),
                schedule=spec.schedule,
                max_pages=spec.max_pages,
                proposed_by=proposer_id,
            )
            .on_conflict_do_nothing(index_elements=["start_url"])
            .returning(Site.id)
        )
        if site_id is None:
            existing = await session.scalar(select(Site.id).where(Site.start_url == start_url))
            if existing is None:
                raise AssertionError("a conflicting site exists")
            return existing, False
        await _audit(
            session,
            proposer_id,
            "site.proposed",
            site_id,
            {},
            {"status": "proposed", "tag_ids": list(tags), **_settings_values(allow, deny, spec)},
            method="cli" if proposer_id is None else "editor",
        )
    return site_id, True


def _settings_values(allow: Sequence[str], deny: Sequence[str], spec: SiteSpec) -> Change:
    return {
        "allow_patterns": list(allow),
        "deny_patterns": list(deny),
        "schedule": spec.schedule,
        "max_pages": spec.max_pages,
    }


async def approve_site(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    reviewer_id: UUID,
    *,
    note: str | None = None,
) -> UUID:
    """``proposed -> approved``; queues the first crawl and returns its job."""
    note = _note(note, required=False)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        if site.status != "proposed":
            raise RegisterError("not_proposed")
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(
                status="approved",
                approved_by=reviewer_id,
                approved_at=func.now(),
                # A reinstated site keeps the reinstatement note unless the approver
                # writes one (P2A-12 a); a new proposal has none.
                review_note=func.coalesce(note, Site.review_note),
                next_crawl_at=next_crawl(site.schedule, datetime.now(UTC)),
                updated_at=func.now(),
            )
        )
        job_id = await enqueue(
            session, "crawl_site", {"site_id": str(site_id)}, created_by=reviewer_id
        )
        await _audit(
            session,
            reviewer_id,
            "site.approved",
            site_id,
            {"status": "proposed"},
            {"status": "approved"},
            roles=sorted(roles),
            self_approval=site.proposed_by == reviewer_id,
        )
    return job_id


async def reject_site(
    factory: async_sessionmaker[AsyncSession], site_id: UUID, reviewer_id: UUID, *, note: str
) -> None:
    """``proposed -> rejected``, with the reviewer's note."""
    checked = _note(note, required=True)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        if site.status != "proposed":
            raise RegisterError("not_proposed")
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(status="rejected", review_note=checked, updated_at=func.now())
        )
        await _audit(
            session,
            reviewer_id,
            "site.rejected",
            site_id,
            {"status": "proposed"},
            {"status": "rejected"},
            roles=sorted(roles),
        )


async def update_site(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    reviewer_id: UUID,
    settings: SiteSettings,
) -> None:
    """A reviewer changes the scope rules, schedule or page budget; audited. Pages that
    fall out of scope are withdrawn by the next crawl."""
    allow, deny = check_patterns(settings.allow_patterns), check_patterns(settings.deny_patterns)
    _check_settings(settings.schedule, settings.max_pages)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        if site.status == "rejected":
            raise RegisterError("rejected")
        before = _settings(site)
        values: dict[str, object] = {
            "allow_patterns": list(allow),
            "deny_patterns": list(deny),
            "schedule": settings.schedule,
            "max_pages": settings.max_pages,
            "updated_at": func.now(),
        }
        if settings.schedule != site.schedule and site.status == "approved":
            base = site.last_crawl_at or datetime.now(UTC)
            values["next_crawl_at"] = next_crawl(settings.schedule, base)
        await session.execute(update(Site).where(Site.id == site_id).values(**values))
        after: Change = {
            "allow_patterns": list(allow),
            "deny_patterns": list(deny),
            "schedule": settings.schedule,
            "max_pages": settings.max_pages,
        }
        if after != before:
            await _audit(
                session,
                reviewer_id,
                "site.settings_changed",
                site_id,
                before,
                after,
                roles=sorted(roles),
            )


async def set_special_category_allow(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    reviewer_id: UUID,
    patterns: Sequence[str],
) -> None:
    """A reviewer sets the paths exempt from the special-category skip (shell-style
    patterns such as ``/reports/health-*``); audited. The next crawl picks them up."""
    cleaned = check_patterns(patterns)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        before = list(site.special_category_allow)
        if before == list(cleaned):
            return
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(special_category_allow=list(cleaned), updated_at=func.now())
        )
        await _audit(
            session,
            reviewer_id,
            "site.special_category_allow_changed",
            site_id,
            {"special_category_allow": before},
            {"special_category_allow": list(cleaned)},
            roles=sorted(roles),
        )


async def request_crawl(
    factory: async_sessionmaker[AsyncSession], site_id: UUID, user_id: UUID
) -> UUID:
    """Queue a crawl of an approved site now (any content role); returns the job, the
    one already queued or running if there is one."""
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await roles_of(session, user_id)
        if not roles:
            raise RegisterError("no_content_role")
        site = await session.scalar(select(Site).where(Site.id == site_id))
        if site is None:
            raise RegisterError("no_site")
        if site.status != "approved":
            raise RegisterError("not_approved")
        job_id = await enqueue(session, "crawl_site", {"site_id": str(site_id)}, created_by=user_id)
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=user_id,
            event="site.crawl_requested",
            metadata={"site_id": str(site_id), "roles": sorted(roles)},
        )
    return job_id


async def schedule_due_crawls(factory: async_sessionmaker[AsyncSession]) -> int:
    """Queue a ``crawl_site`` job for every approved site whose next crawl is due, and
    move its due date on (the crawl sets it again when it finishes)."""
    queued = 0
    async with factory() as session, session.begin():
        due = (
            await session.execute(
                select(Site.id, Site.schedule)
                .where(
                    Site.status == "approved",
                    Site.schedule != "none",
                    Site.next_crawl_at <= func.now(),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for site_id, schedule in due:
            await enqueue(session, "crawl_site", {"site_id": str(site_id)}, created_by=None)
            await session.execute(
                update(Site)
                .where(Site.id == site_id)
                .values(next_crawl_at=func.now() + timedelta(days=SCHEDULE_DAYS[schedule]))
            )
            queued += 1
    return queued


async def withdraw_site(
    factory: async_sessionmaker[AsyncSession],
    site_id: UUID,
    reviewer_id: UUID,
    *,
    reason: str,
) -> list[UUID]:
    """A reviewer withdraws a whole site (P1c-14); returns the ``withdraw_source`` jobs.

    In one transaction: the site becomes ``withdrawn`` with the date and reason and no
    next crawl (so no schedule, "crawl now" or queued crawl runs it again; a running
    crawl stops at its next page, ``app.content.sitecrawl``); every live page is
    ``blocked`` (``site_withdrawn``); every ingested or failed register row of the site
    gets the reason and its ``withdraw_source`` job, the same job a single page's
    withdrawal runs. A row still being ingested is withdrawn as soon as its ingestion
    finishes, because its page is no longer live (findings 1b A2-7). Audited
    ``site.withdrawn`` and, per page, ``source.withdrawal_requested``.
    """
    note = _note(reason, required=True)
    jobs: list[UUID] = []
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        if site.status == "withdrawn":
            raise RegisterError("already_withdrawn")
        if site.status != "approved":
            raise RegisterError("not_approved")
        before: Change = {"status": site.status, "schedule": site.schedule}
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(
                status="withdrawn",
                withdrawn_at=func.now(),
                withdrawal_reason=note,
                next_crawl_at=None,
                updated_at=func.now(),
            )
        )
        await session.execute(
            update(SitePage)
            .where(SitePage.site_id == site_id, SitePage.state == "live")
            .values(state="blocked", reason=SITE_WITHDRAWN, special_category=None)
        )
        rows = (
            await session.execute(
                select(Source.id, Source.status)
                .where(Source.site_id == site_id, Source.status.in_(("ingested", "failed")))
                .order_by(Source.created_at)
                .with_for_update()
            )
        ).all()
        for row in rows:
            await session.execute(
                update(Source)
                .where(Source.id == row.id)
                .values(
                    withdrawal_reason=func.coalesce(Source.withdrawal_reason, note),
                    updated_at=func.now(),
                )
            )
            jobs.append(
                await enqueue(
                    session, "withdraw_source", {"source_id": str(row.id)}, created_by=reviewer_id
                )
            )
            await record(
                session,
                tenant_id=INTERNAL_TENANT_ID,
                actor_user_id=reviewer_id,
                event="source.withdrawal_requested",
                metadata={
                    "source_id": str(row.id),
                    "site_id": str(site_id),
                    "before": {"status": row.status},
                    "after": {"status": row.status},
                    "roles": sorted(roles),
                    "method": "site_withdrawal",
                },
            )
        await _audit(
            session,
            reviewer_id,
            "site.withdrawn",
            site_id,
            before,
            {**before, "status": "withdrawn"},
            roles=sorted(roles),
            count=len(jobs),
        )
    return jobs


async def restore_page(
    factory: async_sessionmaker[AsyncSession], source_id: UUID, reviewer_id: UUID
) -> UUID:
    """A reviewer restores a crawled page they withdrew (P1c-14); returns its site.

    ``source_id`` is the page's withdrawn register row. The page stops being held out
    (``removed``, reason ``restored``), so the next crawl of its site that meets it
    takes it again as a new register row, approved in the site approver's name and
    ingested like any new page. Refused while the withdrawal is still running, for a
    URL any version of which had a takedown recorded (it stays ``taken_down``), and on
    a site that is no longer approved. Audited ``source.restored``.
    """
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        row = await session.scalar(select(Source).where(Source.id == source_id))
        if row is None:
            raise RegisterError("no_source")
        if row.site_id is None:
            raise RegisterError("not_a_crawled_page")
        if row.status != "withdrawn":
            raise RegisterError("not_withdrawn")
        site = await _locked(session, row.site_id)
        if site.status != "approved":
            raise RegisterError("site_not_approved")
        page = await session.scalar(
            select(SitePage)
            .where(SitePage.site_id == site.id, SitePage.source_id == source_id)
            .with_for_update()
        )
        if page is None or (page.state, page.reason) != ("blocked", "withdrawn"):
            raise RegisterError("not_a_withdrawn_page")
        taken_down = await session.scalar(
            select(func.count())
            .select_from(Source)
            .where(
                Source.site_id == site.id,
                Source.canonical_url == page.url,
                Source.takedown_reference.is_not(None),
            )
        )
        if taken_down:
            raise RegisterError("taken_down")
        await session.execute(
            update(SitePage)
            .where(SitePage.site_id == site.id, SitePage.url == page.url)
            .values(state="removed", reason=RESTORED, special_category=None)
        )
        await record(
            session,
            tenant_id=INTERNAL_TENANT_ID,
            actor_user_id=reviewer_id,
            event="source.restored",
            metadata={
                "source_id": str(source_id),
                "site_id": str(site.id),
                "before": {"status": "withdrawn"},
                "after": {"status": "withdrawn"},
                "roles": sorted(roles),
            },
        )
        restored: UUID = site.id
    return restored


async def reinstate_site(
    factory: async_sessionmaker[AsyncSession], site_id: UUID, reviewer_id: UUID, *, note: str
) -> tuple[int, int]:
    """A reviewer reinstates a withdrawn site (P2A-12 a); returns the number of pages
    released and the number kept blocked for a takedown.

    ``withdrawn -> proposed``, with the reviewer's note (required) as the site's review
    note. Never approved here: the site needs a fresh approval (``approve_site``), which
    queues its first crawl; until then nothing crawls it. The start URL is unchanged (it
    stays the site's unique key), the earlier approval is cleared, and the withdrawal's
    date and reason stay on the row as history. The site's register rows stay withdrawn,
    with their history and citations. Pages: every page a takedown was recorded on (any
    version, matched by URL, as ``restore_page`` checks) stays ``blocked`` with reason
    ``taken_down``; every other page held out by the site withdrawal (``site_withdrawn``)
    becomes ``removed`` (``reinstated``), which the crawler treats as a page it has not
    got, so the first crawl after approval admits it as a new row. A page a reviewer
    withdrew on its own stays ``blocked`` (``withdrawn``) and comes back only through
    ``restore_page`` after the approval (owner decision, Oct 25, 2026). Pages blocked for
    any other reason (robots, scope, special category) keep it; the crawl decides them
    again.

    Refused for a site that is not withdrawn (``not_withdrawn``) and while a withdrawal
    of one of its rows is still running (``withdrawal_running``). Audited
    ``site.reinstated`` with the number of pages released (``count``); the note is never
    in the audit trail.
    """
    checked = _note(note, required=True)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        roles = await require(session, reviewer_id, REVIEWER)
        site = await _locked(session, site_id)
        if site.status != "withdrawn":
            raise RegisterError("not_withdrawn")
        running = await session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.site_id == site_id, Source.status.in_(("approved", "ingested", "failed")))
        )
        if running:
            raise RegisterError("withdrawal_running")
        held = SitePage.reason.in_(_RELEASED_ON_REINSTATEMENT)
        taken_down = (
            select(Source.id)
            .where(
                Source.site_id == site_id,
                Source.canonical_url == SitePage.url,
                Source.takedown_reference.is_not(None),
            )
            .exists()
        )
        kept = (
            await session.execute(
                update(SitePage)
                .where(
                    SitePage.site_id == site_id,
                    SitePage.state == "blocked",
                    SitePage.reason.in_(_WITHDRAWN_PAGE_REASONS),
                    taken_down,
                )
                .values(reason=TAKEN_DOWN, special_category=None)
                .returning(SitePage.url)
            )
        ).all()
        released = (
            await session.execute(
                update(SitePage)
                .where(SitePage.site_id == site_id, SitePage.state == "blocked", held, ~taken_down)
                .values(state="removed", reason=REINSTATED, special_category=None)
                .returning(SitePage.url)
            )
        ).all()
        await session.execute(
            update(Site)
            .where(Site.id == site_id)
            .values(
                status="proposed",
                review_note=checked,
                approved_by=None,
                approved_at=None,
                next_crawl_at=None,
                updated_at=func.now(),
            )
        )
        await _audit(
            session,
            reviewer_id,
            "site.reinstated",
            site_id,
            {"status": "withdrawn"},
            {"status": "proposed"},
            roles=sorted(roles),
            count=len(released),
        )
    return len(released), len(kept)
