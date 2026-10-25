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

## 1. Group A

Branch `claude/inspiring-wozniak-e48a12`, from the approved spec at 3ad60fc (D1 to D4
taken). Items P2A-01 to P2A-04, one commit each: eff10c0 (P2A-01), c710a7f (P2A-02),
ac9a1c8 (P2A-03), a945dae (P2A-04). Built and tested on the Instance's host against a
throwaway database and the RAGFlow fake; the live services were not touched (see "Checks
run"). One migration, **0070** (`0070_source_pause`, `down_revision` 0060): Group A
numbers from 0070 so that Groups B to E can use 0061 onwards in parallel, as Phase 1c
Group D did with 0060; the integration step re-parents if needed. Metadata only below.

### P2A-01 Register: `paused` status

| Spec says | Built |
| --- | --- |
| `paused` in `SOURCE_STATUSES`; `paused_at`, `paused_by`, `pause_reason` (required) set if and only if the status is `paused`; no `resumed_at` | Migration 0070 and `app.content.models`: check constraint `pause_recorded` (all three set, the reason not blank, while paused; all three null otherwise). A resume clears them. The downgrade sets paused rows back to `ingested` and says that their RAGFlow documents stay disabled until a person re-enables them |
| `ingested → paused` and `paused → ingested` only, by a content reviewer, audited `source.paused` and `source.resumed` "with reason, reviewer and the RAGFlow outcome" | `register.pause` and `register.resume`. Audited with the reviewer (actor), roles, before and after status, `outcome` `ok` and `count` (documents switched). **The reason text is not in the audit event.** The audit writer allow-lists keys and caps values at 128 characters, and no free-text key exists. Withdrawals keep their reason the same way, on the row only (Phase 1c D-5). The pause reason is on the row while paused and is cleared on resume, so afterwards the trail shows who paused it and when, but not why. Question 1 |
| `paused → withdrawn` through the existing withdrawal request, full cascade; a pause never satisfies a takedown | `request_withdrawal` and the `withdraw_source` job accept `paused`, and the job clears the pause fields when it marks the row withdrawn. **Not in the spec:** a site withdrawal (`withdraw_site`) and the crawl's sweep (a paused page gone from its site) withdraw paused rows too. Before this, both selected only `ingested` and `failed` rows, so a paused page would have outlived its site's withdrawal with its documents in RAGFlow. `record_takedown` and the takedown queue are unchanged: the queue shows the row's status (`paused`) with the same due date |
| The RAGFlow toggle inside the register action, not a job: `RagflowClient.set_document_enabled` (`PATCH`, integer `enabled`, result read from `data.status`) once per entry of `ragflow_document_ids`, idempotent | As specified. `set_document_enabled` sends `{"enabled": 0 \| 1}` and nothing else. It raises `status_mismatch` when `data.status` is not the one asked for, and `unexpected_response` when it is missing. It logs `ragflow.set_document_enabled` with `status`, `error_code` and `latency_ms` only, and its errors carry no RAGFlow message (`include_detail=False`), since the response names the file and its storage location. Entries are switched in dataset ID order, and the IDs come from the register row only. A mapping key that is not a synced dataset's ID (a Phase 0 mapping) is refused (`unmapped_document`) rather than half-paused. The Instance has none (counted Oct 25, counts only). An empty mapping is refused (`no_documents`) |
| Any call fails or returns the wrong status: re-enable what was paused, leave the row `ingested`, return the error code; no partial state | As specified, and **symmetric for resume**: a failed resume disables again what it had enabled and leaves the row `paused`. A failure is audited `source.pause_failed` or `source.resume_failed`, with `error_code`, `outcome` (`undone` or `undo_failed`) and before equal to after, and never `source.paused`. If the undo itself fails, the code returned is `pause_undo_failed` or `resume_undo_failed`, the row keeps its status, and RAGFlow now disagrees with it. `datasets sync` reports that |
| `datasets sync` reports a document whose RAGFlow status disagrees with the register | `datasets.status_mismatches`: one paged listing per mapped dataset (`RagflowClient.list_documents`, new). Each ingested or paused source's documents are compared, with expected `enabled` or `disabled` and found `enabled`, `disabled` or `missing`. The CLI logs `datasets.status_mismatch` (source, tag, dataset, `expected_…_found_…`) and exits 1. The console's "Sync tags" logs `content.status_mismatch` the same way. **Its response is unchanged**: the route's model is a list of per-tag results, and a per-document report did not fit it without a schema change the spec did not ask for |
| `purge_answer_cache` run on pause | Run after the pause commits. A purge failure (cache unreachable) leaves the pause in place, logs `content.cache_purge_failed`, and returns `cache_entries_purged: null`. The corpus fingerprint changed with the status, so the old keys are unreachable anyway. **Found in P2A-04:** the CLI never connected the cache, so a pause from the CLI could not purge. `sources pause` now connects it as the worker does, and logs `error_code: cache_not_purged` when the purge did not happen. The corpus version differs between ingested and paused, so each pause and each resume changes every key. After a resume the key is the pre-pause one again. The entries under it that cited the source were purged at the pause, and the rest answered from the same corpus |
| Tests | `test_pause`: refusals first (an editor and a user with no content role refused, no toggle; `proposed → paused`, `paused → approved`, a failed source's retry and a second pause refused; a blank reason; the database refuses a pause without its record). A failed toggle on the second of two datasets re-enables the first, leaves the row `ingested` and audits no success. A toggle answering the old status is treated the same. An undo that fails is reported, and `datasets sync` then names the document. The payloads the fake RAGFlow received over HTTP through a real `RagflowClient` are exactly `{"enabled": 0}` and `{"enabled": 1}` as integers, with no `status` field. The log names no file. The fake refuses a boolean (102) and ignores `status`, as RAGFlow does. Pause then retrieve through a client tenant's workspace holding the tag returns no chunk of the source and still returns the others. Resume returns them, with no `start_parse` call and nothing deleted. The corpus version (and so the cache key) differs before, during and after, and cached answers citing the source are purged in every tenant. A paused source stays on the takedown queue with its due date and is withdrawn by a withdrawal request. `test_ragflow_client`: integer `enabled`, `data.status` read, `status_mismatch`, `unexpected_response`, an error carrying no RAGFlow message, paged `list_documents`. `test_datasets_sync`: the CLI exits 1 on a mismatch and 0 without one. The RAGFlow fake (`tests/ragflow_fake.py`) learned the toggle, its refusals, status-honouring retrieval and an HTTP transport |

### P2A-02 Pause in every tenant-facing surface

| Spec says | Built |
| --- | --- |
| The file list and download routes already filter on `ingested`, so a paused source is gone; its download answers 404 as for a source outside the workspace, and is audited `download.refused` | The filters needed no change. A paused file asked for directly is now told apart in the service (internal code `paused`). The route answers it **exactly** as `not_found` (404, same body) and audits `download.refused` with `error_code: paused` (before, only the daily cap's refusal was audited). The same applies when a link issued before the pause is redeemed after it: refused, not served, audited. The tenant admin's audit export therefore shows `paused` as the code of such a refusal. The tenant already sees "currently unavailable" on the citation, so this tells it nothing new. Question 2 |
| `provenance_by_document` excludes `paused` too, so `select_context` drops a paused source's chunk | As specified. P2A-03 adds the inherited case |
| A stored citation of a paused source keeps excerpt and provenance, is labelled "currently unavailable" with "View at source" kept, and the label goes on resume | `CitationOut.unavailable` (history only), read live from the register's status, so it goes on resume. The citation panel shows the badge "currently unavailable" and the note "This source is currently unavailable in the research package." Excerpt and "View at source" are unchanged. Withdrawn and superseded keep precedence over it. The two strings are new copy (question 3) |
| The per-site page count counts ingested pages only | Already so: the roll-up is built from the same ingested-only query. Now covered by a test |
| Tests | `test_files`: a paused file is refused as `not_found` and audited with code `paused`. A link issued before the pause is refused and audited, and not marked served. The paused file leaves the list of this tenant and of a second tenant whose workspace holds the tag (D1), the tenant's other files stay, the site's page count drops by the paused page, and after resume the file is listed and downloadable. `test_orchestrator`: the prompt never contains a paused source's chunk when the fake retriever returns it, and neither citations nor stored citations name it. `test_withdraw`: the history route's citation is `unavailable` while paused, otherwise identical, and back to its earlier value after resume. Web: the label, excerpt and link kept, precedence, and no label after resume |

### P2A-03 Pause and the content pipeline

| Spec says | Built |
| --- | --- |
| A changed version of a paused page is admitted as a new approved row that supersedes it; the new version is ingested paused; a reviewer resumes it explicitly | The crawler already admitted it: only unchanged, in-flight or held rows are skipped. Ingestion inherits the pause. **How:** RAGFlow's parser does not read the document's status, so new chunks are written available even under a disabled document (v0.27.2 `rag/svr/task_executor.py`). The pause is therefore applied **after** the parse, in the ingestion's final transaction, under a lock on the predecessor's row, so a reviewer's pause or resume of it waits for this decision. The new row gets status `paused` with the predecessor's reviewer and reason, and is audited `source.ingested` with after status `paused` and `outcome: pause_inherited`. The supersession then withdraws the predecessor as for any new version (`_kind` counts a paused successor). **The parse window:** while the new version is `approved` and parsing, `provenance_by_document` gives it no provenance when its predecessor is paused, so none of its chunks reaches a prompt. Those chunks can still take places among RAGFlow's top results and then be dropped, for the length of one parse. **If the inherited pause cannot be applied,** the new version's documents are deleted and it fails with the code, and its predecessor stays paused and in place. A reviewer retries it, which applies the inherited pause again |
| Manual re-ingestion of a paused source (same link, same title) produces a paused replacement | `replacement_candidates`, `exact_replacement` and `_being_replaced` now count paused sources, so a file at a paused source's link is matched as for an ingested one, and the inheritance above applies |
| Re-tagging a paused source is refused with a code (`paused`) | `approve_retag` refuses `paused`, so the CLI with a reviewer raises it and the console's retag approval answers 409 `paused`. `propose` treats the same content as present (`duplicate` or `retag` with status `paused`), never as a new proposal. A re-tag job that finds its source paused is refused with `paused` |
| (not in the spec) | **A pause waits for an ingestion in flight.** While an `ingest_source` job for the source is queued or running (a re-tag), `pause` and `resume` are refused with `ingestion_in_progress`. A re-tag's new document would otherwise be parsed into available chunks after the pause had switched the others off |
| Tests | `test_pause_pipeline`, refusals first: a re-tag of a paused source refused (CLI path with a reviewer, without one `retag_pending`, the approval refused, nothing uploaded, the same content a `duplicate`). A pause during a re-tag refused, then allowed afterwards, switching the re-tag's document too. An inherited pause that cannot be applied fails the new version, deletes its documents, and leaves the predecessor paused and unretrievable. A new version of a paused source has no provenance while it parses, and gets it once the predecessor is resumed. Then the pipeline: a changed paused page yields a paused successor with the inherited reason and reviewer, its documents disabled, no chunk retrievable through a client tenant's workspace, the old version withdrawn, and the audit outcome recorded. A later unchanged crawl leaves it paused, and resuming makes it retrievable. A re-ingestion at the same link and title of a paused source is ingested paused and supersedes it. `withdraw_source` on a paused source runs the full cascade: every dataset's document deleted, pause fields cleared, stored copy removed, citations in two tenants flagged withdrawn with excerpts blanked, cache purged, and audit `before: paused`, `excerpts_blanked: true`. A paused page gone from its site is withdrawn by the crawl, and a site withdrawal withdraws its paused pages |

### P2A-04 Console, CLI and the tenant-facing path

| Spec says | Built |
| --- | --- |
| Content console: "Pause" and "Resume" on the source detail with a reason field | `POST /api/v1/content/sources/{id}/pause` (`{"reason"}`) and `/resume` (no body). Reviewers only, through the register. The body model forbids extra fields, so a request naming dataset or document IDs is refused 422. RAGFlow failures answer **502** with the code (`ragflow_…`, `…_undo_failed`) and state conflicts answer 409 (`not_ingested`, `not_paused`, `ingestion_in_progress`, `paused`). The source detail shows "Pause reason" and "Pause" on an ingested source, with a line saying a pause does not answer a takedown, and "Resume" on a paused one. The pause record (when, by whom, why) is among the facts. The withdrawal form is offered on a paused source too |
| A `paused` filter and badge on the source list; the pause in the history timeline | `paused` is in the status filter (warning tone). The history shows `paused (ingested → paused)`, `resumed`, `pause failed` with actor, through the existing timeline |
| The operator console's workspace card links to the source list filtered by the workspace's tags | "Sources in its tags" on each workspace with tags, to `/content?tag=…&tag=…`. The source list API takes `tag` repeatedly (any of them), and the register page reads its filters from the link, with a notice naming the tags and "Show every tag". The link reaches the content console, which needs a content role (D4) |
| CLI: `sources pause <id> --reason` and `sources resume <id>`, the same code path | `ask-spore sources pause <id> --as <email> --reason …` and `ask-spore sources resume <id> --as <email>`: `register.pause` and `register.resume`, as the console uses. `--as` is required, as for every reviewer command. Exit 1 with `status: refused` and the code on a refusal |
| Playwright: pause from the console, the file gone from the tenant's library, resume, the file back | `e2e/pause.spec.ts`, against the fake API with both sides answered from one state |
| Tests | `test_content_console`: both routes in the matrix every content route passes (tenant admins and users 403, internal users without a content role 403). A reviewer pauses and resumes from the console, in order: an editor refused, document IDs in the body refused, a blank reason, a resume of an ingested source, a RAGFlow refusal (502, nothing recorded, the failure in the history). Then the pause: detail fields, history, status filter, a second pause refused. Then the resume, with fields cleared. The reason never in a log line. The list takes a workspace's tags. `test_pause`: CLI flags, and the CLI through the register against the database (refusals logged with their code, pause and resume, the cache purged on a CLI pause, the reason never logged). Web: `PauseControls` per status, the summary's pause record, the list badge and history lines, the link and its read-back, the refusal texts, and the client's repeated `tag` and the pause and resume calls |

The operator console's visual baselines for "13c operator tenant workspaces" (desktop and
phone) were regenerated for the new link in the pinned Playwright image; the diff was the
link only.

### Checks run

On the branch head, on the Instance's host. **Not against the live services:** the API
suite ran against a throwaway PostgreSQL 16.15 container (the live `postgres` service's
image, tmpfs, loopback port 55432), the same choice as the Phase 1c release (§5, 2.1),
because the test migrations create cluster-wide roles. RAGFlow and Redis are faked. The
Playwright suites ran in the pinned image of `e2e/visual/run-in-image.sh` on Docker's
bridge network (no host port opened), because the host lacks Chromium's system libraries
and none were installed on the Instance.

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | `All checks passed!` |
| `uv run --directory apps/api ruff format --check .` | `218 files already formatted` |
| `uv run --directory apps/api mypy app` (strict) | `Success: no issues found in 108 source files` |
| `uv run --directory apps/api pytest` (database, `REQUIRE_DB_TESTS=1`) | `1566 passed, 1 deselected` (`test_ragflow_integration`, as in CI); 1528 before Group A |
| `pnpm --dir apps/web lint`, `typecheck`, `test` | `All matched files use Prettier code style!`, `tsc -b` clean, `Tests 168 passed (168)` |
| `pnpm exec playwright test` (pinned image) | `547 passed` |
| `playwright test --config playwright.visual.config.ts` (pinned image) | 124 passed after the 13c update (2 failed before it, the new link) |

`apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` are regenerated. No API
dependency changed. Not run: the live pause drill and evals (P2A-14, release session).

### Questions for the owner

1. **The pause reason in the audit trail (P2A-01).** The spec asks for the reason in
   `source.paused`. The audit writer accepts no free text, so the reason sits on the row
   only, as a withdrawal's does, and is cleared on resume, so after a resume the trail says
   who paused the source and when but not why. Options: (a) keep as built; (b) keep the
   reason on the row after resume (a `last_pause_reason` column; the constraint then covers
   only `paused_at` and `paused_by`); (c) allow-list a `reason` key in the audit writer for
   content events, which puts reviewer-written text into the internal tenant's audit
   export. **Recommendation: (b)**, which keeps the "why" without opening the audit
   allow-list to free text.
2. **The `paused` code in a tenant's audit export (P2A-02).** A refused download of a
   paused file is audited in the tenant's own trail with `error_code: paused`, which its
   tenant admin can export. The user sees the same 404 as for any unknown file. Keep it, or
   record it as `not_found`? **Recommendation: keep**: the history already labels the
   source "currently unavailable", and the code lets a security contact tell a pause from
   an attempt at a file outside the package.
3. **New copy (P2A-02, P2A-04).** The citation badge "currently unavailable" (spec wording),
   its note "This source is currently unavailable in the research package.", and the
   console's "Pause reason", "Pause", "Resume", the takedown line, "Sources in its tags" and
   the refusal texts. UX-08 asks for the owner's approval of new copy. Approve, or give the
   wording?
4. **Inherited pause, the parse window (P2A-03).** RAGFlow writes a new version's chunks as
   available whatever the document's status, so the inherited pause is applied when the
   parse ends. Until then no chunk of it reaches a prompt (no provenance), but RAGFlow can
   return its chunks among the top ten, which are then dropped, so an answer may rest on
   fewer passages for the length of one parse. Accept, or ask for the crawler to hold
   changed versions of a paused page until a reviewer resumes it (no new row until then)?
   **Recommendation: accept.** The window is short, it affects only the tags that hold the
   page, and holding would leave the paused old version as the only one even after a resume.
5. **Migration number.** 0070 on 0060 as above; the integration re-parents if Groups B to E
   chain differently.
