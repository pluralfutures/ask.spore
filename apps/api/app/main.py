"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import cache
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
from app.core.phase0_auth import Phase0AuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Raises ConfigError (and the server exits) if any startup check fails.
    settings = get_settings()
    app.state.settings = settings
    engine = create_engine(settings.secrets.database_url.get_secret_value())
    app.state.db_factory = session_factory(engine)
    cache.connect(settings.secrets.redis_url.get_secret_value())
    log("api.started", status="ok")
    try:
        yield
    finally:
        await cache.close()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="ask.spore API", version="0.0.0", lifespan=lifespan)
    # PHASE 0 ONLY: shared bearer token + X-User-Email. Replaced by Authentik in Phase 1.
    app.add_middleware(Phase0AuthMiddleware)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app()
