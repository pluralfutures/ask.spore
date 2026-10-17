"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as api_v1
from app.chat.orchestrator import Orchestrator
from app.chat.package import phase0_package_tags
from app.chat.prompts import active_prompt
from app.core import cache
from app.core.config import get_settings
from app.core.db import create_engine, session_factory
from app.core.logging import log
from app.core.phase0_auth import Phase0AuthMiddleware
from app.llm.mistral import MistralClient
from app.retrieval.protocol import Retriever
from app.retrieval.ragflow import RagflowRetriever


def create_app(retriever: Retriever | None = None) -> FastAPI:
    """``retriever`` is the RAGFlow retriever (P0-07). Without one, asking returns 503."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Raises ConfigError (and the server exits) if any startup check fails.
        settings = get_settings()
        app.state.settings = settings
        engine = create_engine(settings.secrets.database_url.get_secret_value())
        app.state.db_factory = session_factory(engine)
        app.state.package_tags = phase0_package_tags(settings.config_dir)
        cache.connect(settings.secrets.redis_url.get_secret_value())
        llm = MistralClient(
            settings.models.mistral,
            settings.secrets.mistral_api_key,
            active_prompt(settings, "rewrite").text,
        )
        if retriever is not None:
            app.state.orchestrator = Orchestrator(
                settings=settings,
                db_factory=app.state.db_factory,
                retriever=retriever,
                llm=llm,
                package_tags=app.state.package_tags,
            )
        log("api.started", status="ok" if retriever is not None else "no_retriever")
        try:
            yield
        finally:
            await llm.aclose()
            await cache.close()
            await engine.dispose()

    app = FastAPI(title="ask.spore API", version="0.0.0", lifespan=lifespan)
    # PHASE 0 ONLY: shared bearer token + X-User-Email. Replaced by Authentik in Phase 1.
    app.add_middleware(Phase0AuthMiddleware)
    app.include_router(api_v1)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app(retriever=RagflowRetriever())
