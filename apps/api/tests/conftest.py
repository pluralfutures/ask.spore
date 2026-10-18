"""Shared fixtures.

Database tests need a PostgreSQL 16 server: set TEST_ADMIN_DATABASE_URL to a
superuser/owner DSN (``postgresql://user:pass@host:5432/postgres``). Each test session
creates a throwaway database, migrates it to head and drops it afterwards. Without
the variable the database tests are skipped, unless REQUIRE_DB_TESTS=1 (as in CI),
in which case they fail.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

pytest_plugins = ("tests.chat_fixtures",)

API_DIR = Path(__file__).resolve().parents[1]
SEED_USERS = "analyst@example.org:Test Analyst,Editor@Example.org:Test Editor"


@dataclass(frozen=True)
class MigratedDatabase:
    dsn: str  # asyncpg DSN, owner/superuser

    @property
    def sqlalchemy_url(self) -> str:
        return self.dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


def _with_database(dsn: str, name: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _admin_dsn() -> str | None:
    dsn = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if dsn:
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        pytest.fail("REQUIRE_DB_TESTS=1 but TEST_ADMIN_DATABASE_URL is not set")
    return None


async def _execute(dsn: str, sql: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def migrate(db: MigratedDatabase, revision: str = "head", *, down: bool = False) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["url"] = db.sqlalchemy_url
    if down:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
def database() -> Iterator[MigratedDatabase]:
    admin = _admin_dsn()
    if admin is None:
        pytest.skip("TEST_ADMIN_DATABASE_URL not set")
    name = f"askspore_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_execute(admin, f'CREATE DATABASE "{name}"'))
    db = MigratedDatabase(dsn=_with_database(admin, name))
    previous = os.environ.get("PHASE0_INTERNAL_USERS")
    os.environ["PHASE0_INTERNAL_USERS"] = SEED_USERS
    try:
        migrate(db)
        yield db
    finally:
        if previous is None:
            os.environ.pop("PHASE0_INTERNAL_USERS", None)
        else:
            os.environ["PHASE0_INTERNAL_USERS"] = previous
        asyncio.run(_execute(admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
async def admin_conn(database: MigratedDatabase) -> AsyncIterator[asyncpg.Connection]:
    """Owner/superuser connection: bypasses RLS, used to arrange data."""
    conn = await asyncpg.connect(database.dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def app_conn(database: MigratedDatabase) -> AsyncIterator[asyncpg.Connection]:
    """Connection acting as the application role, so grants and RLS apply."""
    conn = await asyncpg.connect(database.dsn)
    await conn.execute("SET ROLE askspore_app")
    try:
        yield conn
    finally:
        await conn.close()
