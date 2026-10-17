"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import cache
from app.core.config import get_settings
from app.core.logging import log


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Raises ConfigError (and the server exits) if any startup check fails.
    settings = get_settings()
    app.state.settings = settings
    cache.connect(settings.secrets.redis_url.get_secret_value())
    log("api.started", status="ok")
    try:
        yield
    finally:
        await cache.close()


def create_app() -> FastAPI:
    app = FastAPI(title="ask.spore API", version="0.0.0", lifespan=lifespan)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app()
