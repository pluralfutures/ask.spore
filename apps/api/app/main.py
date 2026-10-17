"""FastAPI application entry point."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="ask.spore API", version="0.0.0")

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        # Unauthenticated liveness probe for Compose; carries no data.
        return {"status": "ok"}

    return app


app = create_app()
