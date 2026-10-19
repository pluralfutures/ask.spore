# Phase 0 Findings

Status: updated from the Phase 0 Instance run (Oct 18 to 19, 2026: real corpus, eval set v1, Scaleway
`deepseek-v4.1-flash`; log in `phase-0-instance-run-notes.md`). Assumptions 4 and 5 are answered;
1 (Mistral web search) and 3 (Authentik) remain open. Section 4 still needs the content editor's
side-by-side review in the RAGFlow UI (P0-11). Earlier markers **Needs the real corpus** or
**Needs the Instance** in sections 1 and 3 predate that run.

## 1. Where RAGFlow differs from what the spec assumes

Recorded as found, per `CLAUDE.md` ("follow the real API and record the difference").

| # | Found in | Spec / design assumption | Reality (RAGFlow `v0.27.2`) | What we did |
| --- | --- | --- | --- | --- |
| R1 | P0-02 | "RAGFlow from the official Compose with the bundled embedding model" (spec, Deployment target; Stack Decision, Retrieval) | The RAGFlow image no longer bundles an embedding model (upstream `docker/README.md`: "The RAGFlow Docker image does not include embedding models"). Upstream ships a separate Hugging Face TEI container (`infiniflow/text-embeddings-inference`) as the optional `tei-cpu` / `tei-gpu` profile, with `Qwen/Qwen3-Embedding-0.6B`, `BAAI/bge-m3` or `BAAI/bge-small-en-v1.5` baked in. | `infra/ragflow` runs the TEI container always, default `BAAI/bge-m3` (multilingual). Still self-hosted, so §13 assumption 4 ("self-hosted multilingual model") holds; only the packaging changed. |
| R2 | P0-02, P0-07 | Embedding model fits on the 8 vCPU / 32 GB Phase 0 Instance alongside Elasticsearch | Upstream states RAM to load: Qwen3-Embedding-0.6B ~25 GB, bge-m3 ~21 GB, bge-small-en-v1.5 ~1.2 GB. **Measured** (TEI `cpu-1.8`, bge-m3, 4 vCPU / 16 GB build host, Oct 2026): memory is set by `--max-batch-tokens`, allocated during warm-up and kept resident: 2048 → 2.6 GiB, 4096 → 4.1 GiB, 8192 → 10.4 GiB; upstream's default 16384 passed 15.4 GiB and was killed by the kernel OOM killer. Under ingestion load (all synthetic files, a crawl and the integration tests) TEI at 4096 peaked at 4.13 GiB and the `ragflow` container at 4.55 GiB. | `infra/ragflow` starts TEI with `--max-batch-tokens ${TEI_MAX_BATCH_TOKENS:-4096}`. The per-request limit stays 8192 tokens and RAGFlow chunks are ~512 tokens, so retrieval quality is unaffected; only embedding throughput per batch drops. At 4096, bge-m3 fits the 32 GB Instance (ES 8 GB limit, TEI ~4.1 GB, RAGFlow ~4.6 GB, MySQL/MinIO/Valkey ~1 GB, app ~1 GB). Re-measure on the Instance during P0-11 (8 vCPU may change the figures) and feed P0-20. |
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
| R14 | P0-11 | Chunks from formats without pages carry no page | DOCX, HTML and Markdown chunks come back with `positions = [[1, 0, 0, 0, 0]]`; PPTX slides look the same (`[[n, 0, 0, 0, 0]]`). The retrieval response cannot tell them apart. | `page_or_slide` is documented as meaningful only for `pdf` and `pptx` sources. The orchestrator, which joins the source type by `document_id`, must drop it for other types; flagged for the Group C merge. |
| R15 | P0-11 | n/a | A source ingested under two tags is two RAGFlow documents with different chunk IDs; retrieving across both datasets returns the same text twice. | The orchestrator's de-duplication (P0-14) must compare text or source, not chunk ID. |
| R16 | P0-20 | Retrieval is hybrid: vector similarity can find a chunk that shares no word with the question | A question sharing no term with any chunk returns **no chunks at all**, even with `similarity_threshold = 0` and `vector_similarity_weight = 1.0` ("What is the capital of Australia?", "recipe for a classic French omelette" against the synthetic corpus). With the Elasticsearch backend, the full-text match appears to gate the vector search. | Two consequences. Off-topic questions with no shared term abstain inside RAGFlow, before the threshold matters. And a question phrased entirely differently from the source, or in another language, may retrieve nothing even though bge-m3 is multilingual: test cross-language and paraphrased questions in eval set v1 (section 3, assumption 4). |
| R17 | P0-11 | Parsing long PDFs needs no tuning beyond the Compose defaults | **Measured on the Phase 0 Instance** (Scaleway `GP1-S`, AMD EPYC 7401P, 8 vCPU, AVX2 only, Oct 18, 2026). DeepDoc OCR of a 316-page PDF, five page-range tasks at a time (upstream `MAX_CONCURRENT_TASKS=5`), saturated all 8 vCPUs. TEI then needed 26 to 57 s for a batch of 4 to 16 chunks (upstream `EMBEDDING_BATCH_SIZE=16`), past RAGFlow's hard-coded 30 s embedding read timeout. Each failed page range was re-queued, so the document never finished. Pinning TEI to dedicated cores was slower, not faster (one text 7.3 s → 10.9 s), because TEI then cannot use idle cores. Separately, the CLI's default `--parse-timeout` of 1,800 s expired on the same PDF once embedding worked; the ingest code then deleted the document as designed. | `MAX_CONCURRENT_TASKS=2` and `EMBEDDING_BATCH_SIZE=8` as Compose defaults; a host-specific `cpus: ${RAGFLOW_CPUS:-0}` cap on the `ragflow` container; the Instance sets `RAGFLOW_CPUS=5`, `EMBEDDING_BATCH_SIZE=1` (infra/ragflow/README). With these, the 316-page PDF parsed in 6,063 s with no errors. Long PDFs need `--parse-timeout` of at least 30 s per page on this host. Throughput consequences in section 3, item 5. |

## 1b. Where Mistral differs from what the spec assumes

| # | Found in | Spec / design assumption | Reality | What we did |
| --- | --- | --- | --- | --- |
| M1 | P0-03 | "Mistral EU base URL" as a distinct endpoint | No separate EU hostname could be found; la Plateforme is `https://api.mistral.ai`, described as EU-processed by default (no official regional variant found; Mistral's documentation site was not reachable from the build environment). | `config/models.toml` uses `https://api.mistral.ai` and allow-lists only that host. **To confirm** against the Mistral DPA / zero-retention letter before P0-13 makes the first call, together with §13 assumption 1. |
| M2 | P0-03 | Pinned `mistral-large-<date>` and a pinned small model; Mistral only in Phase 0 (spec, "Not in this phase") | **Checked on the team's account, Oct 18, 2026**, from the Phase 0 Instance. (1) `mistral-large-2512` is not offered on the account's tier: a chat call returns 403 `tier_not_allowed`, and `GET /v1/models` lists no Large model at all. (2) The owner approved `mistral-medium-2604` (Medium 3.5) as a substitute, then `mistral-small-2603`. Both, and every other chat model, return 429 with `x-ratelimit-limit-req-minute: 0` on every call shape (streamed or not, any `max_tokens`, with back-off up to 30 s): the key's workspace has no API request quota, although `GET /v1/models` works. (3) The owner then moved Phase 0 to **Scaleway Generative APIs** (the Stack Decision's second provider), model `deepseek-v4.1-flash`, served under exactly that name by `GET https://api.scaleway.ai/v1/models` (19 models). | `[llm] provider = "scaleway"`; `[scaleway]` with `chat_model`, `rewrite_model` and `judge_model` all `deepseek-v4.1-flash` (one model to cover contractually; the judge grades its own model, D6). The Mistral client and `[mistral]` (`mistral-medium-2604`) stay in place, inactive. **Model names:** Scaleway's are not dated, so the startup check accepts a Scaleway name that is a fixed name without "latest"; Mistral names must still be dated. **Endpoint:** `https://api.scaleway.ai/<SCALEWAY_PROJECT_ID>/v1` (the project form; `/v1` without a project also works), host added to the allow-list. **Reasoning:** DeepSeek reasons by default (14 of 17 output tokens for "ok"); `reasoning_effort = "none"` turns it off (0 reasoning tokens) and is set for answers, rewrites and the judge. **Limits** reported by the API (`x-ratelimit-*`): 600 requests and 5,000,000 tokens per minute for the organisation; the client throttles itself to 5 requests/s and 1,000,000 tokens/min per process. **Open control, not compliant yet:** the Compliance guide's LLM-provider requirements (signed DPA, written ZDR confirmation naming organisation, model and endpoint, EU region pin, and how provider-side prompt caching is treated, since usage reports `cached_tokens`) are not on file for Scaleway. Team-written eval questions on public documents may run; no friendly-client or other real user query until they are. Design documents are updated on the design branch. |

## 1c. Where the Group C build differs from the spec

| # | Found in | Spec says | What we did and why |
| --- | --- | --- | --- |
| C1 | P0-14 | Persist "message, citations, usage"; `done` carries `{message_id, unsupported, tokens_in, tokens_out}` | Migration `0002` adds `messages.outcome` (`answered`, `unsupported`, `abstained`) so a reloaded conversation shows the same badge and "nothing relevant found" state as the live stream. `done` also carries `abstained` and `cached`, which the web app needs. |
| C2 | P0-14 | "Cache by tenant + normalised question + corpus version" | Keyed on the normalised *standalone* (rewritten) query, plus dataset IDs, prompt version and model. Keying on the literal question would serve one conversation's answer to "and in Germany?" in another. The corpus version is a hash over the package's source rows (no trigger needed). |
| C3 | P0-15 | `GET /healthz` among the `/api/v1` routes, "all routes behind P0-06" | The authenticated route is `/api/v1/healthz`. The root `/healthz` stays unauthenticated for the Compose probe (P0-02). |
| C4 | P0-08 / P0-14 | Chunking method per tag: `paper` for reports, `presentation` for PPTX, `naive` for DOCX and web | `sample-analysis` holds both DOCX and PPTX, which would need two methods in one dataset. For Group B (P0-08) to settle; the orchestrator does not depend on it. Settled by Group B: `config/tags.toml` `chunk_method_by_type` sets `presentation` per PPTX document (section 6). |
| C5 | P0-15 | `POST /conversations` returns a conversation the client can use immediately | **Found on the Instance (eval v1, threshold 0.25 run):** `POST /api/v1/conversations/{id}/messages` returned 404 for a conversation created a moment before (`hc-v1-024`; the clean-up `DELETE` was 404 too). `create_conversation` only flushes; the commit happens when the `db_session` dependency exits, which can come after the response is sent, so a fast client can race it. Seen once in about 174 conversations. | **Fixed in `71e592e`.** Write handlers (create conversation, delete conversation, feedback) build the response, commit explicitly, then return; the streaming answer was already committed before `done`, now tested. `tests/test_api.py::test_writes_are_committed_before_the_response` runs create, ask, feedback and delete back to back with a `db_session` whose exit never commits (fails on the old code). The three threshold runs predate the fix. |

## 1d. Where the Group D build differs from the spec

| # | Found in | Spec says | What we did and why |
| --- | --- | --- | --- |
| D1 | P0-17 | `expected_source_ids` "(one or more)" for every item | `out_of_corpus` items must have an empty list; `factual` and `synthesis` need at least one. |
| D2 | P0-17 | `expected_source_ids` are source IDs | Register UUIDs differ per installation and change on re-ingestion, and the research team does not see them. An entry is either the source's `canonical_url` or its register UUID; the harness matches either and warns about entries matching no source. |
| D3 | P0-17 | Eval set items have four fields | Also `id` (stable, unique: `compare` and reviewers need it), optional `labels` and `synthetic`. Schema in `packages/eval/schema/`. |
| D4 | P0-18 | "Calls the orchestrator's retrieval step" | The orchestrator has no separate retrieval entry point (and this group does not change it). The harness runs the same steps with the same building blocks and parameters (`resolve_package`, `RagflowClient.retrieve_chunks`, `provenance_by_document`, `select_context`). It therefore needs read access to Postgres and RAGFlow; exposing retrieval through the API was not an option (CLAUDE.md). |
| D5 | P0-18 | The judge scores sentences against "their cited chunks" | Citations in the API stream carry a 1,200-character excerpt, not the chunk. The harness takes the full chunk text from its own retrieval step (same query, same parameters) by chunk ID and falls back to the excerpt, counting fallbacks (none in the committed runs). |
| D6 | P0-18 | Judge model "Mistral Large" | The judge uses the pinned `chat_model`, so it grades its own model's answers. Self-preference bias is a known risk; consider a separate pinned `judge_model` before results gate releases (Phase 1). `models.toml` `[prompts]` gains `judge = "v1"` (eval only). |
| D7 | P0-18 | Eval runs reflect the configuration under test | The answer cache key (C2) has no retrieval parameters: after a threshold, `top_k` or context-cap change the API serves answers retrieved under the old settings for up to `cache_ttl_seconds`. The harness counts and flags cached answers; the committed runs flushed the cache first. **Proposed orchestrator change (not made here):** add `top_k`, `similarity_threshold`, `max_context_tokens` and the vector weight to the cache key. |
| D8 | P0-19 | The workflow "runs the harness against the Phase 0 Instance" | GitHub-hosted runners cannot reach RAGFlow or Postgres, which have no public listener. The workflow takes the runner label as an input; use a self-hosted runner on the Instance's private network. It has not been run on GitHub: a `workflow_dispatch` workflow can be triggered only once the file is on the default branch. |

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
- **Pages and slides.** `positions` is `[[page, left, right, top, bottom], …]` with 1-based pages (PDF) or slides (PPTX). DOCX, HTML and Markdown chunks get a pseudo-position `[[1, 0, 0, 0, 0]]` (R14). `page_or_slide` is the first entry's page. A `paper` chunk can span a page break, in which case it carries several pages and we report the first.
- **Chunk method per document.** The method is set per dataset, and can be overridden per document with `PATCH …/documents/{id}` before parsing. P0-09 uses that for PPTX files in a dataset whose default is `naive`.
- **Not used:** document download, chunk listing, dataset deletion (integration-test clean-up only), chats, agents and every endpoint that calls an LLM inside RAGFlow.

## 3. Phase 0 assumptions (§13 of the architecture document)

| # | Assumption | Status |
| --- | --- | --- |
| 1 | Mistral web-search tool: available on the EU endpoint for the pinned Large model, covered by the zero-retention letter, priced per call | **Open. Needs the Mistral account.** |
| 2 | RAGFlow: metadata filters across datasets in one call; a file in several datasets does not double-count | **Half answered.** Double-counting answered; metadata filters not tested |
| 3 | Authentik email-link stage: browser binding, single use, per-tenant brands can hide it | **Desk-checked in P1a-02** against authentik `2026.8` source: no browser binding (enforced by the API), single use and expiry yes, per-tenant switch-off done by the API. Not yet run live. See `infra/authentik/README.md` and Phase 1a findings A7 |
| 4 | Self-hosted multilingual embedding meets the eval set's hit-rate target | **Answered for English on this corpus:** factual hit@10 and hit@5 are 100 against the proposed 90 / 80 targets. Cross-language not tested (v1 is all English) |
| 5 | Host sizing: parse throughput and memory on 8 vCPU / 32 GB | **Answered:** memory fits (18 GiB peak); CPU parsing is too slow (about 13 s per PDF page); resize before Phase 1 (item 5) |

**1. Mistral web-search tool.** Nothing could be confirmed from the build environment. No Mistral
key exists, and Mistral's documentation was not reachable (M1). Still to check, all on the team's
account and contract: (a) the tool is offered on `api.mistral.ai` for the pinned
`mistral-large-2512`; (b) calls that use the tool are covered by the zero-retention letter,
including the search query the tool sends to its search backend; (c) price per tool call, on top
of tokens. Together with M1 (the EU endpoint itself) and M2 (dated model IDs). Web search is
Phase 2, so this does not block Phase 1. It does block pulling web search into Phase 1 (§11).

**2. RAGFlow multi-dataset retrieval.**

- *Several datasets in one call:* works. One `POST /retrieval` with the package's dataset IDs
  returned chunks from all three datasets (section 6).
- *Same file in several datasets:* RAGFlow **does** double-count. Each copy is a separate
  document with its own chunk IDs, and it can be chunked differently per dataset (R15, section 6).
  Our orchestrator removes the duplicates: it compares source plus contained text, and live this
  cut 8 chunks to 5 (section 6). So the assumption fails for RAGFlow but holds for the platform.
  Side effect: duplicates use up `top_k` slots before de-duplication. Keep tag overlap low, or
  raise `top_k` when packages overlap heavily.
- *Document-level metadata filters across datasets:* **not tested.** Phase 0 builds no source
  filters. RAGFlow's automatic metadata filters (`auto`, `semi_auto`) send the question to an LLM
  configured inside RAGFlow, which we do not allow (R11). Recommendation for Phase 1: apply
  publisher, date, type and tag filters after retrieval from the source register (architecture
  §5.2 allows either). Raise `top_k` while a filter is active. Only if that proves too lossy,
  test RAGFlow's manual metadata filter on the Instance.
- New: questions with no word in common with the corpus return nothing, whatever the
  threshold or vector weight (R16).

**3. Authentik email-link stage.** Not checked in Phase 0. It needs neither the Instance nor the
corpus, but nobody has done it yet. It is a desk check against the documentation for the pinned
Authentik version, before the Phase 1 spec fixes the login flow. Check: (a) whether a link opened
in a different browser from the one that asked for it is refused, or can be made to be;
(b) whether a link works only once and expires; (c) whether a per-tenant brand or flow can leave
out the email-link option where the operator turned it off; (d) SMTP delivery through Scaleway
Transactional Email.

**4. Embedding quality.** **Answered for English on the Phase 0 corpus** (eval set v1, section 5). Against the targets proposed here before the run, hit@10 ≥ 90 and hit@5 ≥ 80 on `factual` items: **factual hit@10 = hit@5 = 100** (29 items) at thresholds 0.20 and 0.25, and synthesis items also 100. The first expected source is at rank 1 for 40 of 48 in-corpus items. So bge-m3 with RAGFlow's hybrid score (`0.3 × vector + 0.7 × keyword`) meets the targets; there is no case for switching to `mistral-embed` or a hosted embedding on quality grounds. Caveats:

- *The corpus is small* (59 documents, 2,580 chunks) and topically narrow, and many questions share terms with their sources, which the keyword side rewards. Retrieval will get harder as packages grow; keep the targets and re-run per corpus.
- *Not tested:* other languages (v1 is all English, so R16's cross-language risk stands) and paraphrased questions without shared terms. v2 of the set should add both, as proposed.
- *The targets were proposed in this document, not adopted.* The team should confirm them so that later runs gate against them.

**5. Host sizing.** **Answered on the Phase 0 Instance (Oct 18, 2026): memory is ample, CPU is not.**

*Instance:* Scaleway `GP1-S`, fr-par-1, AMD EPYC 7401P (Zen 1, 2017), 8 vCPU, 31 GiB RAM, 90 GB disk, AVX2 only (no AVX-512).

*Memory* (sampled every 10 s from 16:18 to 19:55 UTC, covering the 316-page PDF under full OCR load): `ragflow` 6.0 GiB peak, TEI (bge-m3, `--max-batch-tokens 4096`) 6.0 GiB, Elasticsearch 4.6 GiB, MySQL 0.5 GiB, everything else under 0.5 GiB; all containers together 17.7 GiB, host 18.0 of 31 GiB. Well under the 26 GB resize trigger. *Disk:* 33 GB used before ingestion, 35 GB after.

*Throughput* (RAGFlow's own task times, which exclude queueing; settings of R17):

| Type | Documents | Chunks | Median wall time per document | Parse rate |
| --- | ---: | ---: | ---: | --- |
| PDF (`paper`) | 48 | 2,454 | 170 s | 26.6 s of task time per page (888 pages), two tasks in parallel, so about 13 s per page of wall time; 316 pages took 6,063 s |
| DOCX (`naive`) | 8 | 21 | 9 s | — |
| PPTX (`presentation`) | 3 | 105 | 61 s | — |

The 59 documents took about 7 h of wall time, including the R17 restarts; without them, the whole 60-document corpus (1,264 PDF pages) is about 4.5 to 5 h. That is over the spec's "longer than an afternoon for 40 documents" trigger, so **resize, or move parsing off this host, before Phase 1**.

*Where the time goes:* DeepDoc OCR and layout analysis, not embedding. Embedding was 3,434 s of the 23,616 s of PDF task time (15 %), at 1.4 s per chunk; TEI on this CPU manages about 65 to 100 tokens/s.

*Options* (prices from Scaleway's public pages, Oct 2026; speed-ups are estimates, not measured):

| Option | Cost | Expected effect |
| --- | --- | --- |
| Newer CPU, more cores: `POP2-HC-16C-32G` (AMD EPYC Milan, 16 vCPU) | about €0.43/h | DeepDoc and TEI scale with cores and per-core speed: roughly 2.5 to 3× faster (2× cores, about 1.3 to 1.5× per core). Also lets `MAX_CONCURRENT_TASKS` and `EMBEDDING_BATCH_SIZE` go back up |
| GPU: `L4-1-24G` (NVIDIA L4) with RAGFlow's GPU image and TEI's GPU image | about €0.75/h | Embedding by an order of magnitude or more; OCR and layout several times faster. Largest gain, but a second image set to maintain |
| Ingest on a temporary large Instance only | a few euros per full ingestion | Ingestion is a batch job: run it on a POP2-HC or L4 Instance, keep the small Instance for serving. Needs the volumes (or a RAGFlow export) moved between them |

*Hosted embedding instead of TEI* (Scaleway Generative APIs, `bge-multilingual-gemma2` or `qwen3-embedding-8b`, €0.10 per million tokens, billed per started million): the corpus is about 313,000 tokens by RAGFlow's count, so a full re-embedding costs €0.10 and takes minutes, not hours. But it removes only the 15 % of parse time that embedding takes; OCR stays the bottleneck. It also changes the data flow (corpus text sent to an external API, though EU and public documents) and the embedding model, which means re-embedding everything and re-running the eval. **Recommendation:** keep self-hosted bge-m3 for Phase 1 and fix the CPU (POP2-HC, or a temporary ingestion Instance). Reconsider hosted embedding only if serving-time memory becomes the constraint; it is the owner's call either way, and this session changed no embedding setting.

## 4. Parsing problems (P0-11)

**Real corpus, Oct 18, 2026** (Phase 0 Instance, RAGFlow v0.27.2). 59 of the manifest's 60 documents were ingested: 48 PDF (`paper`), 8 DOCX (`naive`), 3 PPTX (`presentation`); 2,580 chunks. The 376-page PDF on manifest line 15 was not ingested before the session deadline (no eval v1 item names it). Checked for every ingested document by script (chunk sizes, HTML tables, glued words, replacement characters, lines repeated across chunks, page coverage, read from RAGFlow's chunk listing) plus excerpts read by the coding session; the per-document numbers are not committed because they would identify documents. **Still needed: the content editor's side-by-side review in the RAGFlow UI** (checklist section 3), which a script cannot replace for reading order and chart data.

**Corpus deviations from the build spec:** no crawled sites (spec: 2), no own DOCX/PPTX analysis (spec: 10; all 11 DOCX/PPTX files are third-party), every file tagged `sample-reports` (DOCX and PPTX get their own methods there, `f2549cf`).

| Type, method | What we saw | How much it matters |
| --- | --- | --- |
| PDF, `paper` | **Most PDFs are web pages printed to PDF** (45 of 49 have a web page, not a PDF, as their canonical URL). Their chunks are dominated by site navigation, cookie and chat-widget text, footers and phone numbers; one 12-page print yielded only navigation, no article text at all | High: retrieval returns boilerplate, citations quote it, and the article content can be missing. Ingest such pages with `ask-spore crawl` (readability pass, P0-10) or a cleaned export, not a browser print |
| PDF, `paper` | Words glued together in 43 of 48 PDFs (2,151 runs of 26+ letters, e.g. "Minimizefoodwasteinoperations"), mostly display headings, infographic labels and table row labels; another 1,919 camel-case joins | Medium: keyword half of the hybrid score misses those terms; cited excerpts read badly |
| PDF, `paper` | Tables come out as HTML tables with header rows (16 of 48 PDFs have at least one) | Good |
| PDF, `paper` | Very short chunks (2 to 10 characters: logo text, button labels, slide numbers) in design-heavy PDFs; 4 PDFs have a median chunk under 100 characters | Low to medium: wastes `top_k` slots only if retrieved; score threshold usually drops them |
| PDF, `paper` | Recurring section labels and running heads repeat across chunks in 14 of 48 PDFs | Low |
| PDF, `paper` | OCR misreads in navigation text ("YourIndustrv"); no U+FFFD replacement characters anywhere | Low |
| PDF, `paper` | Two different files on the same canonical URL (manifest lines 5 and 6) parse to identical chunks | Medium: the orchestrator de-duplicates only within a source (`select_context`), so the same text fills two context slots and is cited twice. Phase 1: de-duplicate normalised text across sources too |
| DOCX, `naive` | Paragraphs and headings run together without a separator ("…SpotlightElior North America Releases…"), as in the synthetic note; the title repeats in the first chunk | Medium for readability and keyword matching; small DOCX give 1 to 4 chunks each |
| PPTX, `presentation` | One chunk per slide with the slide number; slide headers and survey footnotes repeat on every slide; bullets come out as a leading "." | Good overall; speaker notes are not ingested (synthetic finding), not checked against the real decks |

**Good enough for Phase 1?** PPTX: yes. DOCX: yes, with a pre-conversion step that keeps paragraph breaks if excerpts matter. PDF: yes for publisher reports; **no for printed web pages**, which should be crawled instead; that is a content-workflow change, not a parser setting.

The synthetic observations below came first and remain valid as things to look for.

Observed earlier on the **synthetic** files in `packages/eval/fixtures/corpus/` (RAGFlow v0.27.2, Compose stack). They come from the real parsers, but synthetic files are simpler than real reports, so treat them only as things to look for:

| Type, method | What we saw | Why it matters |
| --- | --- | --- |
| PDF, `paper` | Table rendered as an HTML `<table>` with its caption, which is good. Word spacing lost in places ("Supply-chainbottlenecks", "projectionto7.6GW") and "FICE" read as "FlCE" | Keyword part of the hybrid score misses glued or misread words; citations quote garbled text |
| PDF, `paper` | Section heading "2. Capacity by zone" ended up in the next section's chunk across the page break; that chunk spans pages 1–2 | Citations point to the first page only |
| PPTX, `presentation` | One chunk per slide, slide number kept, text boxes included. **Speaker notes are not ingested** | Content only in notes is not retrievable |
| DOCX, `naive` | Paragraphs run together without separators ("BrightwaterSynthetic", "findingsHeat") | Readability of cited excerpts; keyword matching on run-together words |
| HTML file, `naive` | Navigation text ("Home \| News") kept in the chunk. Crawled pages (P0-10) go through a readability pass and do not have this | Prefer `ask-spore crawl` or Markdown over raw HTML files |
| Unparseable PDF | Ends `DONE` with 0 chunks, not `FAIL` (R13) | Ingestion marks it failed |

## 5. Recommended retrieval parameters for Phase 1

### Real corpus and real model (eval set v1, Oct 18, 2026)

**What ran.** Eval set v1 (`packages/eval/sets/v1.jsonl`, 60 items written by the research team) on the Phase 0 Instance against **59 of the 60 corpus documents** (the 376-page PDF on manifest line 15 was not ingested in time; no v1 item names it). **58 items ran**: `hc-v1-029` and `hc-v1-049` were excluded with `--exclude-label pending-source`, because they name a 2022 report of which the corpus holds only the 2023 edition (owner to confirm). 28 items name register UUIDs instead of canonical URLs because their files share a landing-page URL with other files (`packages/eval/README.md`). Answers, query rewrite and judge: Scaleway `deepseek-v4.1-flash` with reasoning off (M2); the judge grades its own model (D6). RAGFlow v0.27.2, bge-m3, `top_k` 10, vector weight 0.3, context cap 6,000 tokens. Answer cache flushed before each run; no cached answers. Same code (`9f20637` to `11fba99`, harness and API unchanged between runs) and config apart from `[chat] similarity_threshold`, for the API and the harness alike.

| Threshold | Run | hit@5 / hit@10 | Citation precision (factual / synthesis) | Faithfulness | Abstention correctness (out_of_corpus) | Cited-answer rate | Pipeline tokens in / out |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.20 | `20261018T234144Z-9f20637f0c6f` | 100.0 / 100.0 | 79.2 (91.4 / 60.6) | 79.0 | 30.0 (3/10) | 100.0 | 309,844 / 17,497 |
| 0.25 | `20261018T234701Z-a981e7bd8911` | 100.0 / 100.0 | 83.5 (94.0 / 68.0) | 80.9 | 10.0 (1/10) | 100.0 | 303,285 / 17,535 |
| 0.30 | `20261018T235229Z-11fba9927728` | 85.4 / 85.4 | 89.2 (92.5 / 81.1) | 77.9 | 30.0 (3/10) | 85.4 | 152,557 / 10,644 |

`compare` from 0.20: to 0.25, one flagged regression (abstention −20, explained below); to 0.30, hit@5, hit@10 and cited-answer rate −14.6 each. In the 0.25 run one item (`hc-v1-024`) failed with HTTP 404 (C5); it counts as an error, not an answer.

What drives it, from each item's best retrieval score (hybrid score, vector weight 0.3, identical across runs):

| Items | Best score |
| --- | --- |
| factual and synthesis (48) | 0.286 to 0.53, median 0.351; 7 below 0.30 |
| out_of_corpus (10, mostly near misses) | 0.274 to 0.370; 3 below 0.30 |

- **Retrieval is strong on this corpus.** The first expected source is at rank 1 for 40 of 48 items and in the top 2 for 46; hit@5 = hit@10 = 100 at 0.20.
- **No threshold separates near misses.** Out-of-corpus best scores overlap in-corpus ones. At 0.20 and 0.25 no out-of-corpus question abstained without a model call.
- **The model rarely declines.** At 0.20 it answered 7 of 10 out-of-corpus questions with citations instead of saying the corpus cannot answer (prompt rule 3). This is the main quality problem v1 found.
- **0.25 vs 0.20:** no item loses its best chunk. Low-ranked chunks between 0.20 and 0.25 drop out of the context, trimming about 2 % of input tokens and plausibly lifting citation precision by 4 points. The abstention drop (3 → 1) is model nondeterminism, not retrieval: for 9 of the 10 out-of-corpus items the retrieved chunks were identical across the two runs, and `hc-v1-052` still went from declining to answering with 7 citations. With 10 items one flip is 10 points, so abstention needs more items before it can gate releases.
- **0.30** stops 3 out-of-corpus questions but abstains on 7 answerable ones (14.6 points of cited-answer rate). It also halves input tokens and raises citation precision to 89, because weak chunks leave the context. A threshold of about 0.28 (just under the weakest in-corpus best score) would keep that context effect without losing answers on this set; untested.
- **Synthesis citation precision (61 to 81) trails factual (91 to 94):** the model cites passages from sources the team did not list. Some may be legitimate, so the team should review whether `expected_source_ids` lists every source that answers each synthesis item (README rule of thumb).

**Recommendation: `similarity_threshold = 0.25`.** By the rule set before the run ("adopt 0.25 only if v1's cited-answer rate does not drop more than 3 points against 0.20"), 0.25 qualifies: the cited-answer rate is 100 at both. It costs nothing on this corpus and still stops clearly off-topic questions (the synthetic "Sistine Chapel" question scored 0.218). Changed in `config/models.toml` in a separate commit. Do not raise it further for abstention: fix abstention in the prompt (a `corpus_only/v2` that tells the model to compare the question's entity, year and region against the passages before answering, with an eval run) and with more out-of-corpus items in v2 of the set.

### Cost and latency (step 9)

From the 0.20 run (58 questions, no cached answers), end-to-end latency measured by the harness through the API's SSE stream: **median 2.05 s, p95 6.4 s, maximum 10.4 s** (0.25: 1.99 / 5.6 / 8.4 s; 0.30: 1.56 / 3.2 / 4.9 s, fewer passages). Tokens for one full run: pipeline (rewrite + answer) 309,844 in and 17,497 out, that is **5,342 in and 302 out per question**; judge 145,097 in and 9,296 out.

Architecture §10 assumes about 6,000 in and 500 out per answer call and 2 calls per query: measured input is in line, output is 40 % lower. At Scaleway's price for `deepseek-v4.1-flash` as listed by a third-party tracker (about $0.67 per million input and $2.01 per million output tokens, Oct 2026; **check against Scaleway's own price list**), a question costs about $0.004, so §10's 3,000 queries a day (about 90,000 a month) come to roughly **$380 a month**, inside §10's €400 to 600 for Mistral Large. One full eval run costs about $0.36 (judge included).

### Synthetic corpus, mocked Mistral (Oct 18, 2026, kept for comparison)

Everything in this subsection comes from the **synthetic** set (38 items, 7 `out_of_corpus`) on the synthetic
corpus, with Mistral **mocked** (`tests.dev_fake_mistral` for the API, `--mock-mistral` for the
judge). RAGFlow, bge-m3, retrieval, the orchestrator and Postgres are real. It was a
demonstration of the method and a provisional setting; the real-corpus runs above supersede it.
Faithfulness from the mocked judge is a lexical stand-in, and its
movement between runs reflects which items reach the model, not answer quality.

#### Similarity threshold (synthetic)

Three runs, same code, corpus and set. Only `[chat] similarity_threshold` differs, for the API
and the harness alike, and the answer cache was flushed before each run (D7). Results are in
`packages/eval/results/`.

| Threshold | Run | Abstention correctness | out_of_corpus abstained without LLM | Cited-answer rate (factual + synthesis) | hit@5 / hit@10 | Citation precision |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.20 (current) | `20261018T005234Z-857b3ccd0a36` | 28.6 (2/7) | 28.6 | 100.0 (31/31) | 100.0 / 100.0 | 88.7 |
| 0.25 | `20261018T005524Z-1f29494499ba` | 42.9 (3/7) | 42.9 | 100.0 (31/31) | 100.0 / 100.0 | 98.4 |
| 0.30 | `20261018T005642Z-1f29494499ba` | 57.1 (4/7) | 57.1 | 90.3 (28/31) | 90.3 / 90.3 | 100.0 |

`compare` from 0.20: to 0.25, no regression; to 0.30, regressions in hit@5, hit@10 and
cited-answer rate (−9.7 points each) and in the mocked faithfulness.

What drives it, from each item's best retrieval score (hybrid score, vector weight 0.3):

| Items | Best score |
| --- | --- |
| factual and synthesis (31) | 0.269 to 0.529, median 0.355 |
| off-topic: "Sistine Chapel" | 0.218 |
| off-topic: "price of Bitcoin today" | 0.267 |
| off-topic: "capital of Australia", "French omelette" | no chunk at all (R16) |
| near-miss (onshore wind, 2019 heat pumps, gas tariffs) | 0.318 to 0.416 |

- **0.20** lets the "Sistine Chapel" question through to the model, matching the integration
  finding (section 6).
- **0.25** stops it and loses no in-corpus answer. The margin is thin, though: the weakest
  in-corpus item scores 0.269 (`syn-026`, a three-source synthesis question).
- **0.30** also stops "Bitcoin" but abstains on three in-corpus items. Two of them are synthesis
  questions (`syn-026`, `syn-029`) and one is factual (`syn-010`).
- **No threshold catches the near misses.** They score like real questions, so the corpus-only
  prompt's rule 3 ("say so plainly and stop") is the real abstention mechanism. The threshold is a
  cheap first filter. The v1 run with real Mistral will show whether rule 3 holds; abstention
  correctness counts a model that declines (no citations) as correct.

**Recommendation: 0.25, provisionally.** Losing an answer the corpus holds costs more than one
avoidable model call, since the prompt still tells the model to decline. 0.25 is the highest of
the three that kept every in-corpus answer. **Re-run on v1** at 0.20, 0.25 and 0.30, at least.
Adopt 0.25 only if v1's cited-answer rate does not drop more than 3 points against 0.20.
Otherwise keep 0.20 and rely on the prompt.

### Other parameters

| Parameter | Now | Recommendation | Basis | Needs |
| --- | --- | --- | --- | --- |
| `top_k` (RAGFlow `page_size`) | 10 | Try 8 in the next eval run (architecture: 8 to 12) | v1: hit@5 = hit@10 = 100 and the first expected source is at rank 1 or 2 for 46 of 48 items; fewer weak passages raised citation precision at 0.30 (section 5). Duplicates across tags and identical text across sources use up slots (assumption 2, section 4) | One v1 run at `top_k` 8 |
| `knn_top_k` | 1024 | Keep | RAGFlow default candidate pool (section 2) | — |
| `vector_similarity_weight` | 0.3, hard-coded in `app.retrieval.ragflow` | Move to `[chat]` config (and the cache key, D7), then evaluate 0.3, 0.5 and 0.7 on v1 | Scratch probe on the synthetic set: the gap between the best off-topic score and the weakest in-corpus score grows from 0.002 (0.3) to 0.028 (0.5) to 0.054 (0.7). Scores shift upward with the weight, so the threshold must be re-tuned with it (weakest in-corpus item: 0.269 / 0.417 / 0.565) | Real corpus |
| `max_context_tokens` | 6000 | Keep | Matches §10.2's ~6,000 input tokens. The synthetic corpus never reaches it | Real corpus: check how often the cap drops chunks |
| Chunk size | RAGFlow default (~512 tokens) | Keep the default | v1 meets the proposed hit-rate targets (section 3, assumption 4) | — |
| Chunking method | `paper` (PDF), `presentation` (PPTX), `naive` (DOCX, web) | Keep. Decide whether reports are also tagged into `sample-analysis` (section 6: they would be parsed `naive` there) | Section 4, section 6 | Content editor (P0-11) |
| PPTX speaker notes | Not ingested | If our decks keep content in notes, export notes into the slide text or a companion DOCX before ingestion. `syn-018` checks for it | Section 4 | Real decks |

## 6. Integration (Group B + Group C)

Branch `phase-0/integration`: Group C (P0-12 to P0-16) and Group B (P0-07 to P0-11) merged onto `main`, then the fixes below. Checked against the Compose stack on Oct 18, 2026 (RAGFlow v0.27.2, bge-m3 on TEI, Postgres 16).

**Changes made to join the two groups**

- Migration `0003` revises `0002`: chain `0001 → 0002 → 0003`, verified with `upgrade head`, `downgrade base`, `upgrade head`.
- `app.retrieval.ragflow.RagflowRetriever` implements the orchestrator's `Retriever` protocol over Group B's `retrieve()`; `app.main` passes it to `create_app`. `protocol.py` and `types.py` are unchanged.
- R14: `ContextChunk.page_or_slide` is `None` unless the source type is `pdf` or `pptx`, so neither the prompt passage nor the citation carries RAGFlow's pseudo page 1.
- R15: no code change. Group C already de-duplicates by source (via the provenance join) plus normalised-text containment, not by chunk ID. A source under two tags has a different RAGFlow document ID per dataset, so `document_id` would not catch it; the source ID does. Tests added for both notes.
- Test-only: the ingest fixture clears `citations` before `sources` (`ON DELETE RESTRICT`), which failed once both suites shared a database.

**End-to-end pass.** `ask-spore datasets sync` (created, then ok), the five synthetic files ingested (the PDF under `sample-reports` and `sample-analysis`), API run with real RAGFlow and Mistral mocked at the HTTP layer (`apps/api/tests/dev_fake_mistral.py`). One question through `POST /conversations/{id}/messages`:

| Step | Observed |
| --- | --- |
| Retrieval | 8 chunks above 0.2 from all three datasets in 0.8 s |
| De-duplication (R15, live) | The PDF was chunked differently per dataset (`naive` in `sample-analysis`: one 871-character chunk; `paper` in `sample-reports`: smaller chunks). Two `paper` chunks contained in the `naive` chunk and one identical table chunk (different chunk and document IDs) were dropped: 8 → 5 passages |
| Prompt | 5 passages; no UUID- or 32-hex-shaped string anywhere in the request (checked by the fake) |
| Provenance and citations | Both cited passages joined to the PDF's register row (publisher, title, date, canonical URL); dangling marker dropped; `answered` |
| Persistence | Both messages, two citations with RAGFlow chunk IDs, `chat.query` audit event (8 retrieved, 5 in context, cited chunk IDs), title from the question, `expires_at` 30 days |
| Follow-up | Rewrite call made; Markdown source cited with `page_or_slide = null`, PDF with page 1, in the stream and after reload |

**Open points, not fixed here**

- **Threshold 0.2 does not abstain on clearly off-topic questions.** "Who painted the ceiling of the Sistine Chapel?" retrieved one unrelated chunk above 0.2, so the model was called instead of abstaining without a call. Relevant chunks scored 0.25–0.36. Tune with eval set v1 (P0-20); a threshold change needs an eval run.
- **A PDF under `sample-analysis` is parsed with `naive`**, because that tag's `chunk_method_by_type` covers only `pptx`. If reports are meant to be tagged into the analysis dataset too, add `pdf = "paper"` there (P0-08 owner's call).
- Every PDF chunk retrieved here reported page 1. A chunk spanning a page break reports its first page (section 2, "Pages and slides"), so check page accuracy on the real corpus (P0-11).
- Sandbox-only workarounds, nothing committed: a Docker Hub mirror (rate limit), the classic overlay2 storage driver (disk), the proxy CA injected when building the API and web images, and a Compose override lowering Elasticsearch's `memlock` and RAGFlow's `nofile`/`nproc` limits, which this container cannot raise. Elasticsearch runs with `bootstrap.memory_lock=false`, so the memlock limit is unused.
