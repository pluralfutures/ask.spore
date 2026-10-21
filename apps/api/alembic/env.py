"""Alembic environment. Runs as the schema owner from MIGRATIONS_DATABASE_URL.

The API itself connects with DATABASE_URL as the non-owner role askspore_app, so
row-level security applies to it; migrations need the owner.
"""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from app.core.db import create_engine
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    url = context.config.attributes.get("url") or os.environ.get("MIGRATIONS_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATIONS_DATABASE_URL is not set")
    return str(url)


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_engine(_url())  # hide_parameters, as the API's engine
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async())
