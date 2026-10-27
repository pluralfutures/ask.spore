"""Changes to the library clear cached workspace summaries (P2B-05).

A workspace summary (``app.files.service.workspace_summary``) is cached per workspace under
``workspace_summary:<workspace_id>``. It depends on two tables: ``sources`` (the platform's
register, shared by every tenant and mapped to workspaces by tag) and ``workspaces`` (a
workspace's tag selection). Whatever changes the library (a source ingested, re-ingested,
paused, resumed, withdrawn, restored or re-tagged, a crawled page added or withdrawn, a
workspace's tags changed or the workspace deleted) writes one of them, so the hook sits on the
database session instead of on each of the dozens of code paths that write them: a new path is
covered without anyone remembering to call it.

After the transaction commits, every tenant's cached summaries are deleted and the next read
rebuilds them. Every tenant, not only the writer's: the register is shared, and the writer
(the content team's tenant) is rarely the tenant whose workspace holds the source. A rollback
clears nothing. Clears are coalesced: a burst of ingestions runs one clear and, if more
writes landed meanwhile, one more. Failure to reach Redis never fails the write; the cache
entry's own expiry bounds a missed clear.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from app.core import cache
from app.core.logging import log

SUMMARY_PREFIX = "workspace_summary:"
LIBRARY_TABLES = frozenset({"sources", "workspaces"})
_PENDING = "askspore.library_changed"

_task: asyncio.Task[None] | None = None
_again = False


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _context: Any) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if getattr(obj, "__tablename__", None) in LIBRARY_TABLES:
            session.info[_PENDING] = True
            return


@event.listens_for(Session, "do_orm_execute")
def _do_orm_execute(state: ORMExecuteState) -> None:
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) in LIBRARY_TABLES:
        state.session.info[_PENDING] = True


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.info.pop(_PENDING, None):
        schedule_clear()


def schedule_clear() -> None:
    """Clear every tenant's cached summaries in the background (coalesced)."""
    global _task, _again
    if _task is not None and not _task.done():
        _again = True
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no event loop: nothing can be awaited here
    _task = loop.create_task(_clear())


async def _clear() -> None:
    global _again
    while True:
        _again = False
        try:
            await cache.delete_prefix_all_tenants(SUMMARY_PREFIX)
        except RuntimeError:
            return  # the cache is not configured in this process (a CLI without Redis)
        except Exception as exc:
            log("workspace_summary.clear_failed", "warning", error_code=type(exc).__name__)
        if not _again:
            return


async def drain() -> None:
    """Wait for a clear still running (tests, and a process about to exit)."""
    while _task is not None and not _task.done():
        await asyncio.gather(_task, return_exceptions=True)
