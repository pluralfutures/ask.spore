# infra/ragflow

Pinned RAGFlow retrieval tier. Version: see `VERSION` (currently `v0.27.2`).

`docker-compose.yml` is derived from upstream `docker/docker-compose.yml` and
`docker/docker-compose-base.yml` at that tag. Differences, to re-apply on upgrade:

| Change | Why |
| --- | --- |
| Only Elasticsearch, MySQL, MinIO, Redis (Valkey), TEI and RAGFlow (CPU) are kept; profiles removed | Phase 0 uses the Elasticsearch backend on CPU; the other engines are unused |
| Services renamed with a `ragflow-` prefix; hosts passed via environment (`ES_HOST`, `MYSQL_HOST`, ...) | Avoids name clashes with the app's own `postgres` and `redis` when included from `infra/compose.dev.yml` |
| No host ports except the web UI on `127.0.0.1:${RAGFLOW_UI_PORT}` | RAGFlow is internal (CLAUDE.md); the API and workers reach it on the `ragflow` network at `http://ragflow:9380` |
| MCP, admin, Go and HTTPS ports not published | Not used |
| `valkey/valkey:8` pinned to `8.1.10` | No floating tags |
| TEI embedding service always on (upstream: optional `tei-cpu` profile), default model `BAAI/bge-m3` | The RAGFlow image no longer bundles an embedding model |
| `service_conf.yaml.template` and `entrypoint.sh` not mounted; the image's own copies are used | Nothing to override yet |
| Secrets required (`:?`) instead of upstream's well-known defaults | No default passwords |
| `TZ` defaults to `Europe/Paris` | Upstream defaults to `Asia/Shanghai` |

## First run

```
cp infra/ragflow/.env.example infra/ragflow/.env   # then set passwords
docker compose -f infra/compose.dev.yml up -d
open http://localhost:8080                          # register the first account, then set REGISTER_ENABLED=0
```

Create an API key in the UI (avatar → API) and put it in the repository root `.env` as
`RAGFLOW_API_KEY`.

Elasticsearch needs `vm.max_map_count >= 262144` on the host
(`sudo sysctl -w vm.max_map_count=262144`).
