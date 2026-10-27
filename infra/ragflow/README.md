# infra/ragflow

Pinned RAGFlow retrieval tier. Version: see `VERSION` (currently `v0.27.2`).

`docker-compose.yml` is derived from upstream `docker/docker-compose.yml` and
`docker/docker-compose-base.yml` at that tag. Differences, to re-apply on upgrade:

| Change | Why |
| --- | --- |
| Only Elasticsearch, MySQL, MinIO, Redis (Valkey), TEI and RAGFlow (CPU) are kept; profiles removed | Phase 0 uses the Elasticsearch backend on CPU; the other engines are unused |
| Services renamed with a `ragflow-` prefix; hosts passed via environment (`ES_HOST`, `MYSQL_HOST`, ...) | Avoids name clashes with the app's own `postgres` and `redis` when included from `infra/compose.dev.yml` |
| No host ports except the web UI on `127.0.0.1:${RAGFLOW_UI_PORT}`, published by the `ragflow-ui` proxy (Caddy, the public proxy's pinned image), not by RAGFlow | RAGFlow is internal (CLAUDE.md); the API and workers reach it on the `ragflow` network at `http://ragflow:9380` |
| The `ragflow` network is `internal: true` | RAGFlow's Markdown parser fetches every image URL it finds and its guard allows public hosts (P2B-06, `phase-2b-findings.md`); the tier has no route to the internet. Docker publishes no port for a container only on an internal network, hence `ragflow-ui` on a second network. `tests/test_compose_egress.py` guards it. Applying it recreates the network and restarts the tier |
| MCP, admin, Go and HTTPS ports not published | Not used |
| `valkey/valkey:8` pinned to `8.1.10` | No floating tags |
| TEI embedding service always on (upstream: optional `tei-cpu` profile), default model `BAAI/bge-m3` | The RAGFlow image no longer bundles an embedding model |
| TEI started with `--max-batch-tokens ${TEI_MAX_BATCH_TOKENS:-4096}` (upstream default 16384) | Upstream's default keeps more than 15 GiB resident with bge-m3 on CPU; 4096 keeps ~4.1 GiB (findings R2) |
| `COMPOSE_PROFILES=tei-cpu` set in the `ragflow` service environment | RAGFlow only offers TEI as its `Builtin` embedding model when that variable names a `tei-` profile (findings R7) |
| `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE=8` and `cpus: ${RAGFLOW_CPUS:-0}` in the `ragflow` service (upstream 5, 16, no limit); the Phase 0 Instance sets `RAGFLOW_CPUS=5` and `EMBEDDING_BATCH_SIZE=1` in `.env` | On CPU, parallel DeepDoc OCR starved TEI past RAGFlow's hard-coded 30 s embedding timeout and long PDFs never finished (findings R17) |
| `MAX_CONTENT_LENGTH` in the `ragflow` service, upstream default kept (128 MiB) | Per-document size cap; the Instance raises it to 512 MiB in `.env` for one oversized client PDF (findings E7). Parse time grows with page count, not file size |
| `service_conf.yaml.template` and `entrypoint.sh` not mounted; the image's own copies are used | Nothing to override yet |
| Secrets required (`:?`) instead of upstream's well-known defaults | No default passwords |
| `TZ` defaults to `Europe/Paris` | Upstream defaults to `Asia/Shanghai` |

## The web UI from the content console (P1b-05)

The content console links each source's documents to this UI for chunk spot-checks
(`[ragflow] admin_ui_url` in `config/models.toml`, checked at startup to be a loopback
URL). The UI is never published: an operator opens the links over an SSH tunnel to the
Instance, `ssh -L 8080:127.0.0.1:${RAGFLOW_UI_PORT:-8080} <instance>`. The route templates
(`admin_ui_dataset_path`, `admin_ui_document_path`) follow the pinned UI version; check
them when `VERSION` changes.

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
