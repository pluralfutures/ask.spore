# Phase 2A Findings

Oct 25, 2026. Build record of Phase 2A (`phase-2a-build-spec.md`), kept like
`phase-1c-findings.md`: where a build differs from the spec, and why. Metadata only: no
query, question, answer, chunk text, token, key, link or email address is recorded here.
RAGFlow ids are shown as `<id>`.

## P2A-00 probe

Run Oct 25, 2026 on the Phase 1c Instance (`main` at 80ac763). RAGFlow reports
**`v0.27.2`** (`GET /api/v1/system/version` → `{"code": 0, "data": "v0.27.2"}`). Calls were
made from inside the `api` container over the Compose network, the way
`apps/api/app/retrieval/ragflow.py` does it: base URL `http://ragflow:9380` from
`config/models.toml`, service key `RAGFLOW_API_KEY` from the container environment. Dataset
ids were read from our `datasets` table for the three `sample-*` tags. No client dataset
was called.

### Answer

**Mechanism (a) exists on `/api/v1`.** The call is

```
PATCH /api/v1/datasets/<dataset_id>/documents/<document_id>
{"enabled": 0}     # pause: document status "0", every chunk available_int = 0
{"enabled": 1}     # resume: status "1", available_int = 1
```

Three corrections to the spec's wording:

- **The method is `PATCH`, not `PUT`.** v0.27.2 has no `PUT` on that path
  (`api/apps/restful_apis/document_api.py`, `update_document`).
- **The field is `enabled`, an integer 0 or 1.** The request model (`UpdateDocumentReq`,
  `api/utils/validation_utils.py`) declares `enabled: int | None` with `ge=0, le=1`. A JSON
  boolean is refused (`code 102`, "Input should be a valid integer"), although the route's
  docstring says boolean.
- **A `status` field is silently ignored.** The model has `extra="ignore"`, so
  `{"status": "0"}` answers `code 0` and changes nothing: the document stays `"1"` and
  retrieval still returns its chunks. A client that sends `status` would believe it had
  paused a document it had not. P2A-01's `RagflowClient` method must send `enabled` and
  check `data.status` in the response.

### Fields the endpoint accepts

From `UpdateDocumentReq` (v0.27.2). Unknown fields are ignored without error.

| Field | Type | Effect |
| --- | --- | --- |
| `name` | str | Rename (unique within the dataset) |
| `chunk_method` | str, one of the built-in methods | Changes the method and resets the document for re-parse |
| `pipeline_id` | str | Selects or clears pipeline parsing; resets for re-parse |
| `enabled` | int 0 or 1 | **Document status; writes `available_int` on its chunks** |
| `parser_config` | object | Parser settings, chunks kept |
| `meta_fields` | object | Document metadata |
| `chunk_count`, `token_count`, `progress` | int, int, float | Validated as immutable: refused if they differ from the stored value |

What `enabled` does (`update_document_status_only`,
`api/apps/services/document_api_service.py`): when the value differs from the stored status
it updates the document row (`status`) and runs one doc-store update
`{doc_id, must_not exists compile_kwd} → {available_int: status}` in the tenant's index,
scoped to the document's dataset. When the value equals the stored status it does nothing.
Knowledge-compilation chunks (`compile_kwd`) are not touched; our retrieval already sets
`include_knowledge_compilation: false`, so no compiled chunk reaches us either way.

### Response shapes

Toggle, `HTTP 200` in every case; success and failure are told apart by the envelope's
`code`, as `RagflowClient._call` already does. Success (`enabled: 0`), values shown only for
non-identifying fields:

```
{"code": 0, "data": {
  "chunk_count": 1128, "chunk_method": "paper", "content_hash": str,
  "create_date": str, "create_time": int, "created_by": "<id>", "dataset_id": "<id>",
  "id": "<id>", "location": str, "name": str,
  "parser_config": {"image_context_size": int, "llm_id": str, "table_context_size": int},
  "pipeline_id": null, "process_begin_at": str, "process_duration": 6014.92,
  "progress": 1.0, "progress_msg": str, "run": "DONE", "size": 1297545,
  "source_type": "local", "status": "0", "suffix": "pdf", "thumbnail": str,
  "token_count": 76429, "type": "pdf", "update_date": str, "update_time": int}}
```

The response carries the file name and storage location, so the client method must not log
it (log the `code`, status and latency only).

Failures seen:

| Request | Response |
| --- | --- |
| `{"enabled": true}` or `false` | `{"code": 102, "message": "Field: <enabled> - Message: <Input should be a valid integer> - Value: <True>"}` |
| Right document id under another dataset (`sample-analysis`) | `{"code": 102, "message": "the dataset doesn't own the document"}`, nothing changed |
| `{"status": "0"}` | `{"code": 0, "data": {... "status": "1" ...}}`, nothing changed |

Retrieval (`POST /api/v1/retrieval`, the payload `retrieve_chunks` sends: `top_k` 10,
threshold 0.25, vector weight 0.4, `knn_top_k` 1024, every LLM-backed option off), shape
only:

```
{"code": 0, "data": {
  "chunks": [{"content": str, "content_ltks": str, "dataset_id": "<id>",
              "doc_type_kwd": str, "document_id": "<id>", "document_keyword": str,
              "id": "<id>", "image_id": str, "important_keywords": [], "mom_id": str,
              "positions": [[int]], "row_id": null, "similarity": float, "tag_kwd": [],
              "term_similarity": float, "vector_similarity": float}],
  "doc_aggs": [{"count": int, "doc_id": "<id>", "doc_name": str}],
  "total": int}}
```

### Retrieval before, during and after

Target: one `sample-reports` PDF, the dataset's largest document (1128 chunks; the
dataset holds 59 documents, 2580 chunks). The question was the opening words of one of its
own chunks, built in the probe and never printed or stored. Retrieval over `sample-reports`
alone, 10 chunks asked:

| State | Calls | Chunks returned | From the target |
| --- | --- | --- | --- |
| Enabled (baseline) | 5 | 10 each | 8 each |
| After `{"status": "0"}` | 1 | 10 | 8 (no effect) |
| After `{"enabled": 0}` | 5 cycles, plus 4 repeats on the first | 10 each | **0 each** |
| After `{"enabled": 1}` | 5 cycles | 10 each | **8 each** |

The first retrieval issued right after each toggle already reflected it: there was no
window in which a paused document still answered, or a resumed one stayed missing. Other
documents filled the ten places while the target was paused.

The chunk list (`GET …/documents/<id>/chunks`, paged) agreed: 1079 listed chunks,
all `available: true` before, all `false` after `enabled: 0`, all `true` after
`enabled: 1`. The list shows 1079 of the document's 1128 `chunk_count` both before and
after the probe; the gap predates it and was not investigated further (P2A-01 should not
use the chunk list to verify a pause).

**No re-parse.** Document fields before and after the five off/on cycles:

| Field | Before | After |
| --- | --- | --- |
| `id` | unchanged | unchanged |
| `status` | "1" | "1" |
| `chunk_count` | 1128 | 1128 |
| `token_count` | 76429 | 76429 |
| `run` | DONE | DONE |
| `progress` | 1.0 | 1.0 |
| `process_begin_at`, `process_duration` | unchanged | unchanged |
| `update_time` | changed by each toggle | |

Same result on the smallest document (1 chunk), five cycles.

### Timings

Wall clock from the `api` container to RAGFlow, Oct 25, 2026, Instance idle otherwise.
Milliseconds.

| Call | Document size | Samples | Range | Median |
| --- | --- | --- | --- | --- |
| `PATCH enabled 0` | 1128 chunks | 5 | 691 to 2388 (first call slowest) | 996 |
| `PATCH enabled 1` | 1128 chunks | 5 | 749 to 1479 | 922 |
| `PATCH enabled 0` | 1 chunk | 5 | 78 to 94 | 93 |
| `PATCH enabled 1` | 1 chunk | 5 | 84 to 106 | 90 |
| `PATCH enabled 1` on an enabled document (no-op) | 1128 chunks | 1 | 15 | |
| Refused `PATCH` (boolean, wrong dataset) | | 3 | 17 to 19 | |
| `POST /retrieval`, `sample-reports` | | 25 | 596 to 1587 | about 810 |

The toggle cost grows with the document's chunk count (one doc-store update over its
chunks); it is paid once per pause or resume, not per question. Retrieval latency did not
change measurably between the enabled and paused states. Under (a) the retrieval request is
unchanged, so pausing adds nothing to the chat path.

### Scope: per RAGFlow document, which belongs to one dataset

The toggle acts on one RAGFlow document, and a RAGFlow document belongs to exactly one
dataset: the path names the dataset, the handler refuses a document id under any other
dataset, and the doc-store update is scoped to the document's own dataset. So in our terms
the toggle is **per document per dataset**.

That matters because our register keeps one RAGFlow document per tag
(`sources.ragflow_document_ids`, keyed by RAGFlow dataset id). On this Instance all 59
ingested `sample-reports` sources are also tagged with a client tag, and each has a
distinct RAGFlow document id in each of the two datasets (59 of 59 differ, checked in our
database without calling the client dataset). Pausing a source therefore needs one
`PATCH` per entry in its `ragflow_document_ids`, and pausing it under one tag leaves its copy
under the other tag untouched. P2A-01 has to loop over the map and treat a partial failure
as not paused.

### Fallback (b) figures

Not needed, since (a) works; recorded for D2. The largest `sample-*` dataset is
`sample-reports` with 59 documents. `sample-analysis` and `sample-web` hold 0 documents
today (their sources are withdrawn or rejected). An exclusion list for this package would
carry 59 ids; crawled sites would be larger. `document_ids` on `/retrieval` was not probed.

### State at the end

Every document in the three `sample-*` datasets is enabled: `sample-reports` 59 of 59
with status "1" and run `DONE`, the other two empty. Before the probe the same 59 were
enabled. The two probed documents read back with the fields above unchanged.

## 3. Groups D and E

Branch `claude/p2a-group-de`, from `claude/inspiring-wozniak-e48a12` at b5eb872 (the
approved spec), Oct 25, 2026. Items P2A-11, P2A-12 (a) and (b), P2A-13. Built without the
Instance or RAGFlow (RAGFlow faked, PostgreSQL 16 in the session container).

### 3.1 P2A-11 Public files

| Spec says | Built |
| --- | --- |
| Caddy serves `/.well-known/security.txt` (RFC 9116: contact, expiry, preferred languages, the disclosure page URL, signed if the owner holds a key) | `apps/web/public/.well-known/security.txt`, copied into `dist/` by Vite and served by its own `handle` in `infra/caddy/Caddyfile` with `Content-Type: text/plain; charset=utf-8` and `no-cache`. Fields: `Contact` (placeholder `mailto:security-contact@placeholder.invalid`), `Expires` 2027-10-01, `Preferred-Languages: en`, `Policy` (the disclosure page), `Canonical`; `Encryption` is a comment until the owner decides on a key. **Not signed**: no key exists (question 2). The web `Dockerfile` now copies `public/` |
| `/security-disclosure`, drafted under `design/compliance/` and rendered as static HTML in the web build | Draft text and the `security.txt` content: `design/compliance/security-disclosure.md` (DRAFT, with the owner's to-do list). Page: `apps/web/public/security-disclosure.html`, plain HTML and one stylesheet (`public-page.css`; the CSP allows `'self'` only, so no inline style and no script). Caddy rewrites `/security-disclosure` to the file; the file's own name answers 404, so the page has one address |
| Both outside the application and its consent gate | Both `handle`s sit before the web build's catch-all (the `index.html` fallback that loads the app), so the app, its sign-in and its consent gate never run for them, and neither page calls the API |
| The trust page gets a route and is not published until the owner flips a config flag at deploy (the file stays a draft) | `handle /trust { import trust_page_{$ASKSPORE_TRUST_PAGE:unpublished} }` with two snippets: `unpublished` answers 404, `published` serves `trust.html` from the build. Compose passes `ASKSPORE_TRUST_PAGE` from `infra/.env` (default `unpublished`); any other value names no snippet and Caddy refuses to start (checked with `caddy validate`). **Not in the spec, decided here:** the build ships no `trust.html`, so even a flipped flag serves 404 until the owner adds the final page from `trust-page.md` (steps in that file's header). Putting the draft into the build behind the flag would publish its bracketed placeholders on the first flip |
| Status page source decided (D6) and recorded; nothing built | Recommendation below; nothing built |
| Tests: the Compose port test still passes; Playwright: the two files are served without sign-in and without a consent redirect; `security.txt` parses and its `Expires` is within a year | `test_compose_ports` passes unchanged (Caddy's ports did not change; the new `environment` key is not a port). `apps/web/e2e/publicFiles.spec.ts`: with the fake API set to "consent pending" and no signed-in user, `/.well-known/security.txt` answers 200 `text/plain` and parses with `Expires` within a year; `/security-disclosure` shows its heading at its own address, with no app root, no script, no consent button and **no API request**; `/trust`, `/trust.html` and `/security-disclosure.html` are 404. The Vite dev server (which Playwright drives) mirrors the Caddy routes with a small middleware in `vite.config.ts`; with the rewrite removed the disclosure test fails (checked). `apps/api/tests/test_public_files.py`: an RFC 9116 parser, negatives first (no `Contact`, a non-URI contact, `Expires` missing, twice, past, more than a year away, not RFC 3339, no time zone, an unknown field, `http` policy, a stray line, no final line break), then the real file; the file equals the block in the draft; the page loads no script, no inline style and no third-party resource; the routes come before the app's catch-all; the trust flag defaults to `unpublished` in the Caddyfile and Compose; the Dockerfile ships `public/`; the dev mirror names the same paths. One test runs the **real Caddyfile** over HTTP when a `caddy` binary is available (`CADDY_BIN` or `PATH`; skipped in CI, which has none): run here with Caddy 2.11.7 (the pinned version, release checksum verified), both flag states, every route as above |

The `Expires` test fails once the date has passed, or if the file is
edited to more than a year ahead; renewing `Expires` is part of the owner's yearly review
(`security-disclosure.md`). Caddy's other routes are unchanged (`/api/*`, the SSO callbacks,
the catch-all), checked with the local run.

**D6, status page: recommendation.** Take the proposal: a hosted third-party status page,
updated by hand by the operator, until the monitoring stack of idea 3.1 exists. A
self-hosted page on the same host would go down with the service it reports on, and a
monitoring stack is out of this phase. Pick an EU-hosted provider with a free or small plan
that allows subscribers to be switched off (then the page holds no personal data and needs no
DPA beyond the provider's terms; if subscribers are ever enabled, it becomes a sub-processor
and goes into `sub-processors.md` first), publish it on its own subdomain (a CNAME, no change
to Caddy or Compose), list the components the client sees (sign-in, chat answers, file
downloads), and link it from the trust page when that is published. Revisit when 3.1 brings
uptime checks that could post to it automatically.
