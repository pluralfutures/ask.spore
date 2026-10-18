# Phase 0 Findings

Status: complete for what the build environment can establish (P0-20, Oct 18, 2026). Open
items are marked **Needs the real corpus**, **Needs the Instance** or **Needs the Mistral
account**; section 4 waits on the content editor's spot checks (P0-11).

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
| 3 | Authentik email-link stage: browser binding, single use, per-tenant brands can hide it | **Open.** Desk check not done |
| 4 | Self-hosted multilingual embedding meets the eval set's hit-rate target | **Open. Needs the real corpus** (eval set v1). The harness to measure it is ready |
| 5 | Host sizing: parse throughput and memory on 8 vCPU / 32 GB | **Memory answered on a smaller host; throughput needs the Instance** |

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

**4. Embedding quality.** No evidence yet. On the synthetic set, hit@5 and hit@10 are 100 at
thresholds 0.2 and 0.25 (section 5). But that corpus has 5 documents and 12 chunks, so the result
says nothing about bge-m3. To be measured with eval set v1 on the Instance, **needs the real
corpus**. Three points for that run:

- *There is no hit-rate target.* §13 refers to "the eval set's retrieval hit-rate target", but no
  document sets one. Proposal for the team to adopt before the v1 run: hit@10 ≥ 90 and hit@5 ≥ 80
  on `factual` items.
- *The embedding counts for only 30 percent of the score.* RAGFlow's score is
  `0.3 × vector + 0.7 × keyword` with the hard-coded `vector_similarity_weight = 0.3`, and keyword
  matching gates retrieval altogether (R16). A miss is therefore as likely to come from the
  keyword side as from bge-m3. Tune the weight (section 5) before switching to `mistral-embed`.
  Switching would send all corpus text to Mistral at ingestion, a change to the compliance
  guide's data flow even under the same DPA.
- *v1 should include* paraphrased questions and questions in the other languages clients will use
  (R16).

**5. Host sizing.** Memory (R2, measured on a 4 vCPU / 16 GB build host): TEI with bge-m3 at
`--max-batch-tokens 4096` keeps about 4.1 GiB resident, and the `ragflow` container peaked at
4.6 GiB under ingestion. A snapshot from this group's run, idle after ingestion and with
Elasticsearch capped at 3 GiB for the sandbox, showed: TEI 4.2 GiB, RAGFlow 4.2 GiB,
Elasticsearch 2.1 GiB, MySQL 0.5 GiB, everything else under 0.2 GiB. With Elasticsearch at its
8 GB limit, the stack needs about 18 GB, which fits the 32 GB Instance with headroom. Disk: the
images alone are about 24 GB, and Elasticsearch stops accepting writes below 3 GB free (R12). The
§10.3 figure of 200 GB block storage is ample; do not go below 100 GB. Throughput: after the first
synthetic file, the next four (7 chunks in all) finished within 22 s on 4 vCPU. That does not
predict 30+ real PDFs through DeepDoc. **Needs the Instance:** time the P0-11 ingestion per file type and record
`docker stats` peaks during it, then resize before Phase 1 if parsing 40 documents takes longer
than an afternoon or memory peaks above about 26 GB.

## 4. Parsing problems (P0-11)

The real sample corpus has not been ingested yet: it needs the content and the Phase 0 Instance. The content editor fills this section from the spot checks in `design/specs/phase-0-corpus-checklist.md`.

Observed so far on the **synthetic** files in `packages/eval/fixtures/corpus/` (RAGFlow v0.27.2, Compose stack). They come from the real parsers, but synthetic files are simpler than real reports, so treat them only as things to look for:

| Type, method | What we saw | Why it matters |
| --- | --- | --- |
| PDF, `paper` | Table rendered as an HTML `<table>` with its caption, which is good. Word spacing lost in places ("Supply-chainbottlenecks", "projectionto7.6GW") and "FICE" read as "FlCE" | Keyword part of the hybrid score misses glued or misread words; citations quote garbled text |
| PDF, `paper` | Section heading "2. Capacity by zone" ended up in the next section's chunk across the page break; that chunk spans pages 1–2 | Citations point to the first page only |
| PPTX, `presentation` | One chunk per slide, slide number kept, text boxes included. **Speaker notes are not ingested** | Content only in notes is not retrievable |
| DOCX, `naive` | Paragraphs run together without separators ("BrightwaterSynthetic", "findingsHeat") | Readability of cited excerpts; keyword matching on run-together words |
| HTML file, `naive` | Navigation text ("Home \| News") kept in the chunk. Crawled pages (P0-10) go through a readability pass and do not have this | Prefer `ask-spore crawl` or Markdown over raw HTML files |
| Unparseable PDF | Ends `DONE` with 0 chunks, not `FAIL` (R13) | Ingestion marks it failed |

## 5. Recommended retrieval parameters for Phase 1

Everything here comes from the **synthetic** set (38 items, 7 `out_of_corpus`) on the synthetic
corpus, with Mistral **mocked** (`tests.dev_fake_mistral` for the API, `--mock-mistral` for the
judge). RAGFlow, bge-m3, retrieval, the orchestrator and Postgres are real. Treat it as a
demonstration of the method and a provisional setting. **Every recommendation must be re-run on
eval set v1 with the real corpus and Mistral before `config/models.toml` changes**; this group
changed no configuration. Faithfulness from the mocked judge is a lexical stand-in, and its
movement between runs reflects which items reach the model, not answer quality.

### Similarity threshold

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
| `top_k` (RAGFlow `page_size`) | 10 | Keep 10 (architecture: 8 to 12) | Synthetic hit@5 = hit@10, so no signal. Duplicates across tags use up slots (assumption 2) | Real corpus: if v1 hit@5 ≈ hit@10, try 8 to cut context tokens |
| `knn_top_k` | 1024 | Keep | RAGFlow default candidate pool (section 2) | — |
| `vector_similarity_weight` | 0.3, hard-coded in `app.retrieval.ragflow` | Move to `[chat]` config (and the cache key, D7), then evaluate 0.3, 0.5 and 0.7 on v1 | Scratch probe on the synthetic set: the gap between the best off-topic score and the weakest in-corpus score grows from 0.002 (0.3) to 0.028 (0.5) to 0.054 (0.7). Scores shift upward with the weight, so the threshold must be re-tuned with it (weakest in-corpus item: 0.269 / 0.417 / 0.565) | Real corpus |
| `max_context_tokens` | 6000 | Keep | Matches §10.2's ~6,000 input tokens. The synthetic corpus never reaches it | Real corpus: check how often the cap drops chunks |
| Chunk size | RAGFlow default (~512 tokens) | Keep the default; tune only if v1 misses its hit-rate target | R2: chunks are ~512 tokens | Real corpus |
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
