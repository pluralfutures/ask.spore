# infra

| File | Purpose |
| --- | --- |
| `compose.dev.yml` | Local stack: Postgres 16, Redis 7, API, web dev server, and RAGFlow (included from `ragflow/`) |
| `ragflow/` | Pinned RAGFlow Compose, `VERSION`, `.env.example`; see its README for differences from upstream |
| `caddy/`, `monitoring/` | Phase 1+ |

## Local stack

```
cp infra/ragflow/.env.example infra/ragflow/.env      # set passwords
docker compose -f infra/compose.dev.yml up -d
```

| Service | URL (host) | Notes |
| --- | --- | --- |
| API | http://127.0.0.1:8000/healthz | |
| Web | http://127.0.0.1:5173 | Vite dev server, `src/` bind-mounted |
| RAGFlow UI | http://127.0.0.1:8080 | Loopback only; the UI port also proxies RAGFlow's API, so never publish it beyond loopback or the firewall |
| Postgres | 127.0.0.1:5432 | db `askspore`; owner `askspore` (`POSTGRES_PASSWORD`, dev `askspore-dev`) runs migrations; the API logs in as `askspore_app` (`APP_DB_PASSWORD`, dev `askspore-app-dev`), which is not the owner, so row-level security applies |
| Redis | 127.0.0.1:6379 | |

All host ports bind to `127.0.0.1`. RAGFlow's Elasticsearch, MySQL, MinIO, Redis, TEI
and HTTP API (`9380`) publish nothing; the API container reaches RAGFlow at
`http://ragflow:9380` on the `ragflow` network.

The one-shot `migrate` service runs `alembic upgrade head` as the owner before the API
starts. `PHASE0_INTERNAL_USERS` in the root `.env` lists the users the first migration
seeds. `infra/postgres/10-app-role.sh` creates the `askspore_app` login role on a fresh
volume only.

To run the API or web app on the host with `--reload` instead (the commands in
`CLAUDE.md`), start only the backing services so the ports do not clash:

```
docker compose -f infra/compose.dev.yml up -d postgres redis ragflow
set -a; . ./.env; set +a          # DATABASE_URL, MIGRATIONS_DATABASE_URL, secrets
uv run --directory apps/api alembic upgrade head
```

Host requirement for Elasticsearch: `sysctl -w vm.max_map_count=262144`.
Disk: the RAGFlow and TEI images are about 24 GB together.
