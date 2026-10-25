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
the catch-all), checked with the local run. The development `web` container in `infra/compose.dev.yml` now mounts `apps/web/public` read-only beside `src`, so the dev server serves the same files (follow-up commit; `test_public_files` asserts the mount).

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

### 3.2 P2A-12 (a) Withdrawn-site reinstatement

No migration: `sites.status` already allows `proposed`, and `site_pages.reason` takes any
code.

| Spec says | Built |
| --- | --- |
| A reviewer reinstates a withdrawn site: back to `proposed` with a required note, `site.reinstated` audited | `app.content.sites.reinstate_site`, a **reviewer** action (an editor is refused): `POST /api/v1/content/sites/{id}/reinstate` (`{"note"}` only, the existing `NoteIn`), a "Reinstate site" form on a withdrawn site's page, and `ask-spore sites reinstate <site_id> --as <email> --note …`. The note becomes the site's review note (the approval keeps it unless the approver writes another: `approve_site` now writes `coalesce(note, review_note)`, which changes nothing for a new proposal, whose note is empty). Audited `site.reinstated` (before `withdrawn`, after `proposed`, roles, `count` = pages released); **the note is never in the audit trail or a log line**, as for the withdrawal reason. Refused: a site that is not withdrawn (`not_withdrawn`), and while a row of the site is still `approved`, `ingested` or `failed`, that is while its withdrawal jobs have not all run (`withdrawal_running`; not in the spec: reinstating mid-withdrawal would race the jobs) |
| The start URL is unchanged; the site needs a fresh approval | Start URL, tags, licence and settings untouched; `approved_by`, `approved_at` and `next_crawl_at` cleared, so nothing crawls the site (schedule, "crawl now", a stale queued `crawl_site` all need `approved`) until `approve_site` runs, which queues the first crawl as for a new site. The withdrawal's date and reason stay on the row as history: the console shows a reinstated site as "Reinstated after a withdrawal on …, not crawled until a reviewer approves it again" |
| Its withdrawn pages stay withdrawn; the crawl's block list keeps every page blocked for a takedown | No register row changes: every withdrawn row stays withdrawn with its history and citations. A page is kept `blocked` when any version of its URL on the site has a `takedown_reference` (the check `restore_page` makes), and its reason is set to `taken_down`, so the crawler's reason check skips it; the crawler's own takedown check would refuse it anyway |
| Other withdrawn pages of the site are released so the next crawl admits them as new rows | Pages held out by the site withdrawal (`site_withdrawn`) **or by a reviewer's earlier withdrawal of the page** (`withdrawn`) become `removed` with reason `reinstated`, which the crawler treats as a page it has not got: the first crawl after the approval admits each as a new row in the new approver's name (no `supersedes_id`) and ingests it. Pages blocked for other reasons (robots, scope, special category, duplicate) keep their reason; the crawl decides them again. Question 4 |
| Tests | `test_sites`: `test_a_reinstatement_is_refused_to_an_editor_without_a_note_or_too_early` (negatives: an approved site, withdrawal jobs still queued, a blank note, an editor, an unknown site; no event written), `test_a_reinstated_site_is_proposed_not_approved_and_nothing_crawls_it` (status, cleared approval, same start URL, note kept, no schedule, "crawl now" refused, a stale crawl job fetches nothing, the audit event without the note), `test_a_reinstated_site_keeps_taken_down_pages_out_and_admits_the_others_as_new` (a page with a takedown, a page a reviewer withdrew and a page the site withdrawal held out: after approval and a crawl the takedown URL is still refused and blocked, the two others are new ingested rows with new IDs, the old rows stay withdrawn). `test_content_console`: the route is refused to tenant admins and users like every content route; `test_a_reviewer_reinstates_a_withdrawn_site_from_the_console` (codes, 403 for an editor, 422 for a missing, blank or extra field, the response counts, approval then three new rows). `test_withdraw`: the CLI's flags (note required) and its log line (count and status, no note; a refusal exits 1 with the code). Web: the form needs a note and offers no approval, the reinstated-site notice, the `reinstated` page reason |

### 3.3 P2A-12 (b) Public holidays in the takedown clock

| Spec says | Built |
| --- | --- |
| `config/holidays.toml`: a calendar of dates per named region, one region marked active in the same file | `active = "<region>"` and `[regions.<name>]` tables (`name`, `dates` as TOML local dates). The repository file has `none` (no dates) **active**, and a draft `france` region with the eleven national public holidays of metropolitan France for 2026 and 2027 (not Alsace-Moselle's two extra days). The active region is the owner's choice (question 5); until then the clock keeps the Monday-to-Friday rule, the stricter one, since a holiday only ever moves a due date later |
| Consulted by `working_days_after` so the takedown clock skips them | `working_days_after`, `takedown_due_on` and `record_takedown` take the calendar's dates (`holidays`, default empty); the content API and `sources takedown` in the CLI pass `Settings.holidays`. **Not in the spec:** the queue's SLA timer (`TakedownItem.working_days_left`, shown on the takedown queue and the source page) counts on the same calendar, so "days left" agrees with the due date. Due dates already stored are not recomputed: a change of calendar applies to requests recorded after it |
| The file is validated at startup like `models.toml` (no network, no library) | `app/core/holidays.py`, read with `tomllib` by `load_settings` (API, worker, CLI and the eval harness): problems are added to the same `ConfigError` list. Refused: a missing file, invalid TOML (an impossible date such as `2026-13-01` or `2026-02-30` is a TOML error), a string, a number or a date-time instead of a date, dates out of order or repeated, an unknown key, a region without a name, a region name that is not lower-case, no region, an `active` that names no region. `Settings` gains `holidays` (a frozen `HolidayCalendar`). No dependency added |
| An empty calendar keeps today's Monday-to-Friday rule | `active = "none"` (or any region with `dates = []`) gives the same dates as before for every start day |
| Tests: a request on the day before a listed holiday is due one working day later than today's rule; a malformed date refuses startup | `tests/test_holidays.py`, negatives first: 15 malformed files each refuse startup with a problem naming the file, a missing file refuses it, and the module imports only the standard library. Then: Tue Nov 10, 2026 with Nov 11 listed is due Nov 25 instead of Nov 24; a licence breach is still due the same day; the empty calendar matches the old rule for two weeks of start days; a weekend holiday changes nothing, two holidays add two days, a holiday on the request day does not count; the SLA timer counts on the same calendar; the repository file loads with `none` active; the draft `france` region matches the national holidays, its movable dates checked against Easter computed in the test. `test_content_console::test_the_takedown_clock_follows_the_configured_calendar` (the route's due date, the queue and the source page's timer use the startup calendar); `test_withdraw::test_cli_takedown_uses_the_configured_calendar`. The test harnesses' stand-in settings carry `holidays`; `write_config` writes an empty calendar |

### 3.4 P2A-13 Logging policy follow-up

| Spec says | Built |
| --- | --- |
| `IngestResult.error` and `_Failure` messages keep the error **code** only; the detail is dropped, not logged | `_Failure(code, context=None)` now builds its own message, `<code>` or `<code>: <context>`, and the context is only ever our own values: a tag name, the run constant (`FAIL` or `CANCEL`, the only non-`DONE` values a finished document can have), an exception class name, `clean-up of an interrupted run` or `re-tag`, and on a failed clean-up `clean-up failed (<ragflow code>), documents left in RAGFlow`. A `RagflowError` contributes `error_code` (`ragflow_<code>`) and nothing else. **Not in the spec, same reason:** a failed parse no longer copies RAGFlow's `progress_msg` (RAGFlow's own text, which can name the file or quote it) into the message; the non-RAGFlow messages (`no_file`, `no_dataset`, `staged_<code>`, `parse_timeout`, `internal_error`) are code-first too, so every row's `error` starts with its code. The CLI never printed `IngestResult.error` (it logs `error_code`); with the change nothing it could print carries RAGFlow text |
| (the source row's `error`, shown in the console detail) | Rows written from now on hold the code-first message. **Not in the spec:** a row that failed before this change may still hold RAGFlow's text on the Instance, and no migration was planned for it, so `source_detail` (`_shown_error`) shows the row's `error` only when it starts with the code of the source's latest `source.failed` audit event, and that code otherwise. No RAGFlow message is shown either way; the stored text of such a row disappears at its next retry or withdrawal (the release session may count them: `status = 'failed'` rows) |
| Add `RagflowError` to the handlers the static scan in `test_logging_policy` checks, as `FetchError` and `IngestError` are | The P1c-04 rule is generalised to `scan_coded_errors`: a caught `FetchError` may be read through `.code` and `.status` or handed to `_refused`; a caught `RagflowError` through `.code` and `.error_code` only (no sink: `_refused` does not take it); a handler catching both may use only what both allow. Bare `raise` is allowed. Note: the spec's "as `FetchError` and `IngestError` are" — `IngestError` is not in the scan (its messages are ours and name a file, a URL or a tag, by design); `FetchError` is. Run over the code before this change, the scan reports exactly the four sites the review named (`ingest.py` 256, 270, 343, 497 at b5eb872) |
| Tests: the scan rejects a handler that passes `str(exc)` of a `RagflowError` to a log, a message or an exit; the source row's `error` after a parse failure is a code | `test_logging_policy`: `test_a_ragflow_error_message_never_leaves_its_handler` (11 handlers × 3 ways of catching: `str`, f-string, `.args`, the bare name to `log`, into `_Failure`, into an appended error, into `SystemExit`, `repr` into an `IngestResult`, `.detail`, `_refused`), `test_a_handler_of_both_coded_errors_may_use_only_what_both_allow`, `test_a_ragflow_error_handler_may_use_the_code` (six allowed forms, the app's own), `test_every_ragflow_error_handler_in_the_app_is_scanned` (nine handlers today, none a violation). `test_ingest::test_a_ragflow_errors_text_never_reaches_the_source_row_or_the_log` (an upload refused with synthetic detail text: row and result `ragflow_102`; a parse failure with that text as `progress_msg` and a failing clean-up: `parse_failed: sample-reports FAIL; clean-up failed (ragflow_500), …`; the text is in neither, nor in the log). `test_content_console::test_the_console_shows_a_failure_as_a_code_never_ragflows_text` (the detail shows the code-first message; a row given a pre-P2A-13 RAGFlow message shows the audited code, and the response carries none of the text). Six existing tests that asserted RAGFlow's text on the row now assert its absence |
