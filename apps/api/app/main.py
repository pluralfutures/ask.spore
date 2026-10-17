"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Raises ConfigError (and the server exits) if any startup check fails.
    app.state.settings = get_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ask.spore API", version="0.0.0", lifespan=lifespan)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app()
