# Phase 0 Findings

Status: in progress. Filled in as Phase 0 work items land; P0-20 completes it.

## 1. Where RAGFlow differs from what the spec assumes

Recorded as found, per `CLAUDE.md` ("follow the real API and record the difference").

| # | Found in | Spec / design assumption | Reality (RAGFlow `v0.27.2`) | What we did |
| --- | --- | --- | --- | --- |
| R1 | P0-02 | "RAGFlow from the official Compose with the bundled embedding model" (spec, Deployment target; Stack Decision, Retrieval) | The RAGFlow image no longer bundles an embedding model (upstream `docker/README.md`: "The RAGFlow Docker image does not include embedding models"). Upstream ships a separate Hugging Face TEI container (`infiniflow/text-embeddings-inference`) as the optional `tei-cpu` / `tei-gpu` profile, with `Qwen/Qwen3-Embedding-0.6B`, `BAAI/bge-m3` or `BAAI/bge-small-en-v1.5` baked in. | `infra/ragflow` runs the TEI container always, default `BAAI/bge-m3` (multilingual). Still self-hosted, so §13 assumption 4 ("self-hosted multilingual model") holds; only the packaging changed. |
| R2 | P0-02, P0-07 | Embedding model fits on the 8 vCPU / 32 GB Phase 0 Instance alongside Elasticsearch | Upstream states RAM to load: Qwen3-Embedding-0.6B ~25 GB, bge-m3 ~21 GB, bge-small-en-v1.5 ~1.2 GB. **Measured** (TEI `cpu-1.8`, bge-m3, 4 vCPU / 16 GB build host, Oct 2026): memory is set by `--max-batch-tokens`, allocated during warm-up and kept resident: 2048 → 2.6 GiB, 4096 → 4.1 GiB, 8192 → 10.4 GiB; upstream's default 16384 passed 15.4 GiB and was killed by the kernel OOM killer. Under ingestion load (synthetic corpus) TEI at 4096 stayed at ~4.1 GiB. | `infra/ragflow` starts TEI with `--max-batch-tokens ${TEI_MAX_BATCH_TOKENS:-4096}`. The per-request limit stays 8192 tokens and RAGFlow chunks are ~512 tokens, so retrieval quality is unaffected; only embedding throughput per batch drops. At 4096, bge-m3 fits the 32 GB Instance (ES 8 GB limit, TEI ~4 GB, RAGFlow ~4 GB, MySQL/MinIO/Valkey ~1 GB, app ~1 GB). Re-measure on the Instance during P0-11 (8 vCPU may change the figures) and feed P0-20. |
| R3 | P0-02 | "RAGFlow services bind to the Compose network only" and "a reachable RAGFlow UI on localhost" | The web UI container's nginx also reverse-proxies RAGFlow's HTTP API (`/api/v1/...`, `/v1/...`). Publishing the UI therefore also publishes the API on that port. | UI published on `127.0.0.1` only in dev. On the Phase 0 Instance the port must stay firewalled to the team's IPs (spec already requires this). The platform API reaches RAGFlow on the Compose network at `http://ragflow:9380`, never via the UI port. |
| R4 | P0-02 | n/a | Upstream `.env` sets `API_PROXY_SCHEME=python`; without it the container starts nginx but not the Python API server. | Set explicitly in `infra/ragflow/docker-compose.yml`. |
| R5 | P0-02 | n/a | Health endpoints: `GET /api/v1/system/ping` → `pong`; `GET /api/v1/system/healthz` → `{"db","doc_engine","redis","storage","status"}`. Legacy `/v1/system/healthz` also answers. `/v1/system/ping` is 404. | Container healthcheck uses `/api/v1/system/healthz`. |
| R6 | P0-02 | Images pinned | Upstream Compose uses floating tags for Valkey (`valkey/valkey:8`), SeekDB and the sandbox executor (`:latest`). | Valkey pinned to `8.1.10`; SeekDB and sandbox are not used and were dropped. |
| R7 | P0-07 | TEI is RAGFlow's embedding model once the container runs | RAGFlow offers TEI as its `Builtin` embedding model (and as the default for new accounts) only if the RAGFlow container's `COMPOSE_PROFILES` contains `tei-`. P0-02 removed profiles, so new accounts had no embedding model and every parse would fail. | `COMPOSE_PROFILES=tei-cpu` set in the `ragflow` service environment (a marker only; the Compose file has no profiles). Datasets are also created with an explicit `embedding_model` from `config/models.toml` (`BAAI/bge-m3@Builtin`), so they never depend on the account default. |
| R8 | P0-07 | Datasets can be looked up by name or id | `GET /api/v1/datasets?name=…` (or `?id=…`) for a dataset that does not exist returns `code 102`, "User '…' lacks permission for dataset '…'": the same error as a real permission failure. | The client lists all datasets (paged) and filters locally. |
| R9 | P0-08 | Creating a dataset whose name exists fails, so creation is naturally idempotent | `POST /api/v1/datasets` with an existing name succeeds and creates `name(1)`. | `ask-spore datasets sync` looks up existing datasets by exact name before creating. |
| R10 | P0-07 | `ragflow-sdk` pinned to the server version covers the calls | `ragflow-sdk` 0.27.2 is synchronous `requests` with no timeout parameter, and lags the 0.27.2 server: it sends the deprecated `top_k` to `/retrieval` (server logs a deprecation warning; the replacement is `knn_top_k`) and parses via the legacy `POST /datasets/{id}/chunks` rather than `POST /datasets/{id}/documents/parse`. | The client uses `httpx` for every call (Stack Decision allows it "otherwise"); using the SDK from the async API would block the event loop and could hang without bound. Stack Decision updated. |
| R11 | P0-07 | Retrieval is a pure search call | `/api/v1/retrieval` options `keyword`, `cross_languages`, `toc_enhance`, `use_kg` and an `auto`/`semi_auto` `meta_data_filter` make RAGFlow send the question to the chat LLM configured inside RAGFlow. `include_knowledge_compilation` (default `true`) adds LLM-compiled chunks. | The client sends all of these explicitly off and excludes knowledge-compilation chunks; a contract test asserts it. No LLM is configured inside RAGFlow. |
| R12 | P0-07 | n/a | Elasticsearch refuses to allocate shards (cluster red, every insert fails with `unavailable_shards_exception`) once free disk drops below the high watermark set in `infra/ragflow/docker-compose.yml` (3 GB). The pinned images alone are ~28 GB. | Host sizing (P0-20): give the Instance disk headroom well above image size + corpus + 3 GB. A failed insert surfaces as document `run = FAIL` with the ES error in `progress_msg`, which ingestion records. |
| R13 | P0-09 | A file RAGFlow cannot parse ends in `run = FAIL` | A corrupt PDF ends `run = DONE`, `progress = 1`, with 0 chunks. Infrastructure errors (R12) do end in `FAIL`. | Ingestion treats `DONE` with 0 chunks as failed (`no_chunks`). Any failed source has its RAGFlow documents deleted, so nothing of it can be retrieved or cited. |

## 1b. Where Mistral differs from what the spec assumes

| # | Found in | Spec / design assumption | Reality | What we did |
| --- | --- | --- | --- | --- |
| M1 | P0-03 | "Mistral EU base URL" as a distinct endpoint | No separate EU hostname could be found; la Plateforme is `https://api.mistral.ai`, described as EU-processed by default (no official regional variant found; Mistral's documentation site was not reachable from the build environment). | `config/models.toml` uses `https://api.mistral.ai` and allow-lists only that host. **To confirm** against the Mistral DPA / zero-retention letter before P0-13 makes the first call, together with §13 assumption 1. |
| M2 | P0-03 | Pinned `mistral-large-<date>` and a pinned small model | Dated IDs could not be verified against the live model list from the build environment. Pinned `mistral-large-2512` (Mistral Large 3) and `mistral-small-2603` as the best available information. | Startup enforces the dated format and rejects `-latest`. **To confirm** with `GET /v1/models` on the team's account before P0-13; change only `config/models.toml`. |

## 2. RAGFlow endpoints and parameters used

Confirmed against RAGFlow `v0.27.2` (server source in the image and live calls from the Compose stack; responses recorded under `apps/api/tests/fixtures/ragflow/`). Base URL `ragflow.base_url` from `config/models.toml` (`http://ragflow:9380`, Compose network only) plus `/api/v1`; `Authorization: Bearer $RAGFLOW_API_KEY`. Every response is an envelope `{"code": 0, "data": …}`; failures are `{"code": n, "message": …}`, usually with HTTP 200 (`100` server error, `101` argument error, `102` data/permission error).

| Operation (`app.retrieval.ragflow`) | Call | Parameters we send | What we read |
| --- | --- | --- | --- |
| `create_dataset` | `POST /datasets` | `name`, `chunk_method`, `permission: "me"`, `embedding_model` (`BAAI/bge-m3@Builtin`) | `id`, `name`, `chunk_method`, `embedding_model` |
| `list_datasets` | `GET /datasets` | `page`, `page_size=100`, `orderby=create_time`; no `name`/`id` filter (R8) | list of datasets |
| `upload_document` | `POST /datasets/{dataset_id}/documents` | multipart `file` (one file per call) | `data[0].id`, `run = "UNSTART"` |
| `set_document_chunk_method` | `PATCH /datasets/{dataset_id}/documents/{document_id}` | `{"chunk_method": …}` | envelope only |
| `start_parse` | `POST /datasets/{dataset_id}/documents/parse` | `{"document_ids": [...]}` | `data.success_count` |
| `get_document` (poll) | `GET /datasets/{dataset_id}/documents` | `id`, `page=1`, `page_size=1` | `docs[0].run` (`UNSTART`, `RUNNING`, `CANCEL`, `DONE`, `FAIL`, `SCHEDULE`), `progress` (−1 on failure), `progress_msg`, `chunk_count` |
| `delete_documents` (P0-09, failed ingestion only) | `DELETE /datasets/{dataset_id}/documents` | `{"ids": [...]}`; never `delete_all` | `data.deleted` |
| `retrieve_chunks` / `retrieve` | `POST /retrieval` | `dataset_ids`, `question`, `page=1`, `page_size=top_k`, `similarity_threshold`, `vector_similarity_weight=0.3`, `knn_top_k=1024`, and off: `keyword`, `cross_languages=[]`, `toc_enhance`, `use_kg`, `highlight`, `include_knowledge_compilation` (R11) | `data.chunks[]`: `id`, `document_id`, `dataset_id`, `content`, `similarity`, `positions` |

Notes:

- **`top_k` means two things.** The spec's `top_k=10` is the number of chunks returned, which RAGFlow calls `page_size`. RAGFlow's own `knn_top_k` (formerly `top_k`) is the vector-recall candidate pool; we keep its default 1024.
- **Score.** `similarity` is RAGFlow's hybrid score, `vector_similarity_weight × cosine + (1 − weight) × keyword score`, and `similarity_threshold` filters on it. On the synthetic corpus, clearly relevant chunks scored 0.25–0.33 with weight 0.3, so a threshold of 0.2 is plausible but must be tuned with eval set v1 (P0-20).
- **Pages and slides.** `positions` is `[[page, left, right, top, bottom], …]` with 1-based pages (PDF) or slides (PPTX); DOCX, HTML and Markdown chunks have none. `page_or_slide` is the first entry's page. A `paper` chunk can span a page break, in which case it carries several pages and we report the first.
- **Chunk method per document.** The method is set per dataset, and can be overridden per document with `PATCH …/documents/{id}` before parsing. P0-09 uses that for PPTX files in a dataset whose default is `naive`.
- **Not used:** document download, chunk listing, dataset deletion (integration-test clean-up only), chats, agents and every endpoint that calls an LLM inside RAGFlow.

## 3. Phase 0 assumptions (§13 of the architecture document)

To be answered by P0-20.

## 4. Parsing problems (P0-11)

To be filled by P0-11.

## 5. Recommended retrieval parameters for Phase 1

To be filled by P0-20.
