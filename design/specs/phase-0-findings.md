# Phase 0 Findings

Status: in progress. Filled in as Phase 0 work items land; P0-20 completes it.

## 1. Where RAGFlow differs from what the spec assumes

Recorded as found, per `CLAUDE.md` ("follow the real API and record the difference").

| # | Found in | Spec / design assumption | Reality (RAGFlow `v0.27.2`) | What we did |
| --- | --- | --- | --- | --- |
| R1 | P0-02 | "RAGFlow from the official Compose with the bundled embedding model" (spec, Deployment target; Stack Decision, Retrieval) | The RAGFlow image no longer bundles an embedding model (upstream `docker/README.md`: "The RAGFlow Docker image does not include embedding models"). Upstream ships a separate Hugging Face TEI container (`infiniflow/text-embeddings-inference`) as the optional `tei-cpu` / `tei-gpu` profile, with `Qwen/Qwen3-Embedding-0.6B`, `BAAI/bge-m3` or `BAAI/bge-small-en-v1.5` baked in. | `infra/ragflow` runs the TEI container always, default `BAAI/bge-m3` (multilingual). Still self-hosted, so §13 assumption 4 ("self-hosted multilingual model") holds; only the packaging changed. |
| R2 | P0-02 | Embedding model fits on the 8 vCPU / 32 GB Phase 0 Instance alongside Elasticsearch | Upstream states RAM to load: Qwen3-Embedding-0.6B ~25 GB, bge-m3 ~21 GB, bge-small-en-v1.5 ~1.2 GB. With Elasticsearch's 8 GB limit, MySQL, MinIO and RAGFlow's own ~4 GB, bge-m3 at the stated figure would not fit in 32 GB. | Open. Measure actual TEI memory with bge-m3 on the Instance during P0-11; if it does not fit, options are a larger Instance, the GPU profile, or `mistral-embed` (§13 assumption 4 already names it as the fallback). Feeds the host-sizing answer in P0-20. |
| R3 | P0-02 | "RAGFlow services bind to the Compose network only" and "a reachable RAGFlow UI on localhost" | The web UI container's nginx also reverse-proxies RAGFlow's HTTP API (`/api/v1/...`, `/v1/...`). Publishing the UI therefore also publishes the API on that port. | UI published on `127.0.0.1` only in dev. On the Phase 0 Instance the port must stay firewalled to the team's IPs (spec already requires this). The platform API reaches RAGFlow on the Compose network at `http://ragflow:9380`, never via the UI port. |
| R4 | P0-02 | n/a | Upstream `.env` sets `API_PROXY_SCHEME=python`; without it the container starts nginx but not the Python API server. | Set explicitly in `infra/ragflow/docker-compose.yml`. |
| R5 | P0-02 | n/a | Health endpoints: `GET /api/v1/system/ping` → `pong`; `GET /api/v1/system/healthz` → `{"db","doc_engine","redis","storage","status"}`. Legacy `/v1/system/healthz` also answers. `/v1/system/ping` is 404. | Container healthcheck uses `/api/v1/system/healthz`. |
| R6 | P0-02 | Images pinned | Upstream Compose uses floating tags for Valkey (`valkey/valkey:8`), SeekDB and the sandbox executor (`:latest`). | Valkey pinned to `8.1.10`; SeekDB and sandbox are not used and were dropped. |

## 2. RAGFlow endpoints and parameters used

To be filled by P0-07.

## 3. Phase 0 assumptions (§13 of the architecture document)

To be answered by P0-20.

## 4. Parsing problems (P0-11)

To be filled by P0-11.

## 5. Recommended retrieval parameters for Phase 1

To be filled by P0-20.
