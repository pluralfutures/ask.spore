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
| TEI started with `--max-batch-tokens ${TEI_MAX_BATCH_TOKENS:-4096}` (upstream default 16384) | Upstream's default keeps more than 15 GiB resident with bge-m3 on CPU; 4096 keeps ~4.1 GiB (findings R2) |
| `COMPOSE_PROFILES=tei-cpu` set in the `ragflow` service environment | RAGFlow only offers TEI as its `Builtin` embedding model when that variable names a `tei-` profile (findings R7) |
| `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE=8` in the `ragflow` service (upstream 5 and 16) | On CPU, parallel DeepDoc OCR starved TEI past RAGFlow's hard-coded 30 s embedding timeout and long PDFs never finished (findings R17) |
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
