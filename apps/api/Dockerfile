FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
RUN pip install --no-cache-dir uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /srv/api
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
# Installs the project itself, which provides the `ask-spore` command.
RUN uv sync --locked --no-dev

RUN useradd --system --uid 10001 api
# The content store ([files] content_root, P1a-14) is a named volume. Docker creates a
# fresh volume with the mount point's owner, so it must belong to the api user before
# the first run, or ingestion fails at its first store with "Permission denied".
RUN mkdir -p /srv/ask-spore/content && chown api:api /srv/ask-spore/content
USER api

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
# No access log: request paths carry single-use download tokens (P1a-14), and the API
# logs metadata itself (app.core.logging).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
