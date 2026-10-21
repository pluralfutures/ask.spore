"""Database engine, ORM base and tenant-scoped sessions.

The API connects as the non-owner role ``askspore_app`` (DATABASE_URL), so
PostgreSQL row-level security applies to every query. Each tenant-scoped
transaction sets ``app.tenant_id`` with ``set_config(..., is_local => true)``:
the value lives only for that transaction, so a pooled connection never carries
one request's tenant into another. With no tenant set, every policy matches zero
rows (fail closed).

Two narrower paths do not run under a tenant scope, each in a transaction that
switches to a dedicated NOLOGIN role (``SET LOCAL ROLE``) which ``askspore_app`` can
assume but does not inherit:

- ``askspore_auth`` (revision 0005): pre-authentication lookups for sign-in links;
- ``askspore_operator`` (revision 0006): the operator console, outside tenant RLS.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

APP_ROLE = "askspore_app"
AUTH_ROLE = "askspore_auth"
OPERATOR_ROLE = "askspore_operator"
TENANT_SETTING = "app.tenant_id"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# Roles the API may switch to inside one transaction; never built from input.
_SET_ROLES = frozenset({AUTH_ROLE, OPERATOR_ROLE})


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(database_url: str, *, connect_args: dict[str, Any] | None = None) -> AsyncEngine:
    # hide_parameters: a DBAPIError's message never carries the statement's bound
    # values, which include message text, feedback comments and prompts (findings §12).
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=connect_args or {},
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Scope the session's current transaction to ``tenant_id`` for RLS."""
    if not isinstance(tenant_id, UUID):
        raise TypeError("tenant_id must be a UUID")
    await session.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": TENANT_SETTING, "value": str(tenant_id)},
    )


@asynccontextmanager
async def role_session(
    factory: async_sessionmaker[AsyncSession], role: str
) -> AsyncIterator[AsyncSession]:
    """A transaction run as ``role`` (one of the fixed roles above), with no tenant set."""
    if role not in _SET_ROLES:
        raise ValueError(f"not a role the API may assume: {role}")
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL ROLE {role}"))
        yield session


@asynccontextmanager
async def tenant_session(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID
) -> AsyncIterator[AsyncSession]:
    """A session whose transaction is scoped to ``tenant_id``; commits on success.

    The body may ``await session.commit()`` itself (API write handlers do, so the row
    is durable before the response goes out, C5). SQLAlchemy 2.x allows that inside
    ``session.begin()``: the block's exit then finds its transaction already closed and
    does nothing. ``app.tenant_id`` ends with the committed transaction, and SQLAlchemy
    refuses any further statement on the session inside the block
    (``InvalidRequestError``), so nothing can run unscoped after the commit.
    """
    async with factory() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session
