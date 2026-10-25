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

## 2. Groups B and C

Branch `claude/p2a-group-bc`, from `claude/inspiring-wozniak-e48a12` at b5eb872 (the approved
spec). Built Oct 25, 2026. One commit per item; P2A-09 is withdrawn (audit disposal stays in
the backlog, and every document keeps its "no disposal path yet" note).

| Item | Commit |
| --- | --- |
| P2A-05 usage section | 58ac406 |
| P2A-06 consent status per user | 2bbf3ec |
| P2A-07 audit export hardening | 0df2fa8 |
| P2A-08 time-boxed support access | 5cf8031 |
| P2A-10 policy and checklist documents | 5c330fb |

**Migration: 0065** (`support_grants` and the role `askspore_support`; down_revision
**0060**). Group A's `paused` migration runs in parallel: at integration, re-parent 0065
onto Group A's head (one `down_revision` line).

### P2A-05 Usage section

| Spec says | Built |
| --- | --- |
| One aggregation route per tenant, from `audit_events` and `citations` under the tenant-scoped session | `GET /api/v1/admin/usage` (`app/usage/dashboard.py`) under the request's tenant session, every query also naming the tenant. **From `audit_events` only**: the top sources come from the `chat.query` events' `cited_source_ids`, not from `citations`. Citations go with the chat history (30 days at most, none for a tenant on "no history"), so counting them would make the figure depend on the tenant's retention; the events are kept 12 months and give one count per answer that cited the source, for every tenant |
| Questions per day for the last 30 days by answer mode | Every `chat.query` event per UTC day and `mode`, including refused and failed questions (an attempt to ask). Only days with activity are returned; the page shows every day of the period with zeroes (question 8) |
| Active users per day | Distinct `actor_user_id` of `chat.query` per UTC day; the count only |
| Top ten cited sources by title and publisher | Title, publisher and the number of answers citing it; no source ID. A withdrawn or paused source still counts by its title (nothing of its content) |
| Month-to-date cost per model for a tenant with the external-models entitlement | `usage_ledger` for the current UTC month, every model (EU ones too), tokens in and out and cost, as the operator's spend tab shows them; `costs` is `null` without the entitlement |
| No query text, per-user ranking or conversation IDs; the schema asserted body-free | `test_logging_policy::test_the_usage_response_carries_counts_only`: the response's field names (nested models included) equal an allow-list disjoint from body and identifier names, so a new field fails until classified |
| Tests | `test_admin_usage.py`: zero rows for a tenant with no events while another tenant is busy; two seeded tenants each see their own counts, and no user ID, email, conversation or message ID appears; costs only with the entitlement; the route is admin-only. Web: `usage.test.ts` (filled days, totals, month boundary), the `UsageView` render tests |

### P2A-06 Consent status per user

| Spec says | Built |
| --- | --- |
| `AdminUserOut` gains `consent_version` and `consent_current` | As specified, `consent_current` against `[consent] version` (`app.consent.gate.active_version`). The operator's user list uses the same schema, so it shows the status too |
| The notice version named in the section heading | "Users · notice v1". The version comes from `GET /consent`, which the consent gate already loads (same query key), rather than from a new field |
| Tests | `test_consent.py`: with notice v2 active, a user who accepted v1 is `false`, a user who never accepted is `null`/`false`, the admin who accepted v2 is `true`; neither field is in `/me`. Web: `consentStatus`, `usersHeading` |

### P2A-07 Audit export hardening

| Spec says | Built |
| --- | --- |
| An explicit allow-list of event names beside the event catalogue | `app/audit/events.py`: `EXPORTED_EVENTS` and `OPERATOR_ONLY_EVENTS`, disjoint, and `DYNAMIC_EVENTS` for the one name built at run time (`source.{status}` in ingestion). The export filters on `EXPORTED_EVENTS` |
| `workspace.prompt_tenant_name_match`, `model.fallback` and every `operator.` event not about this tenant's users stay out | Out: those two, `chat.query`, `chat.feedback`, `conversation.deleted`, and the operator's configuration events (`operator.entitlements_changed`, `login_policy_changed`, `sso_source_changed`, `tenant_created`, `workspace_created`, `workspace_tags_changed`, `source_downloadable_changed`), which the old `operator.` prefix exported (question 2). In: `operator.admin_invited`, `invitation_resent`, `user_removed`, and `operator.granted` / `revoked` (about the internal tenant's own users), plus the support events of P2A-08 |
| A test fails when an event name is added without being classified | `test_audit_events.py` parses `app/`, finds every call to `record` and to any helper that forwards its own `event` argument (`audit_sign_in`, the register's and the sites' `_audit`, `_review`), reads literal names, literal step lists looped over (the site crawl) and listed f-strings, and fails on an unclassified name or one it cannot read; tests prove it catches each path. **Beyond the spec**, `record()` also refuses an unclassified name at run time (`UnclassifiedAuditEvent`), so nothing reaches the table unclassified (question 4) |
| Classified ahead | `source.paused` and `source.resumed` (Group A, P2A-01) and `site.reinstated` (Group D, P2A-12) are in `OPERATOR_ONLY_EVENTS` already, so those builds pass the catalogue test if they use these names |
| `until` beside `since` | Both whole UTC days, inclusive; default `until` today and `since` 90 days before it; `since` after `until` is 422 `invalid_period` |
| Page the export in date windows when a window exceeds the row cap; the response says so | Paged by a **cursor**, not by date windows: a single day can exceed 10,000 rows, which no date window can split. A file holds at most 10,000 rows; `X-Audit-Export-Complete: false` and `X-Audit-Export-Next: <created_at>|<id>` say there is more, and the next call passes it as `after` with the same dates. The file name carries the dates; `tenant_admin.audit_exported` records `count` and `status` (`complete` or `partial`) |
| One export per minute per admin, with `app.auth.ratelimit` | `IpRateLimiter(1, 60 s)` keyed by the admin's user ID (its SHA-256, in memory, per API process, as for the sign-in limits); 429 `rate_limited` with `Retry-After`. A continuation part counts as an export (question 3) |
| "Download" with date fields on the Audit section | From and To dates (default the last 90 days) and "Download the next part" when the API says there is more |
| Tests | Every catalogued name seeded (plus an unclassified one) yields exactly the exported set, nothing of another tenant; the second call within a minute is 429 and a second admin is not limited; `since`/`until` bounds; a period over a lowered cap is paged with no row lost or repeated (ties on `created_at` included). Web: the query builder, the 90-day default, the client call's URL and headers; Playwright: the page's download asks for the chosen dates and then the next part |

### P2A-08 Time-boxed support access

| Spec says | Built |
| --- | --- |
| `support_grants`: tenant-scoped, RLS, `tenant_id`-first index | Migration 0065: RLS enabled and forced with `tenant_isolation`, indexes `(tenant_id, created_at)` and `(tenant_id, conversation_id)`, `UNIQUE (tenant_id, id)`, checks on scope, conversation, duration (15 to 240), expiry (`created_at` plus the duration), note (1 to 500 characters). The application role inserts and may update `revoked_at` only; a trigger refuses un-revoking, reopening a closed grant and any other change. `test_schema` lists the table (RLS, index, zero rows for another tenant, none without a tenant) |
| Granted by a tenant admin: scope `settings` or one conversation chosen from their own list; 15 minutes to 4 hours, default 1 hour; a note | `POST /api/v1/admin/support-grants`. "Their own list" read as **the admin's own live conversations** (the only conversation list an admin has); another user's conversation is refused as `conversation_not_found` (question 1). The settings scope is what a tenant admin sets: retention, each workspace's defaults and current additional instructions (entitlements, login policy and users the operator already sees) |
| The operator sees open grants on the tenant's console page and reads the granted scope through dedicated routes that check scope and expiry on every call | A "Support access" tab: the open grants (scope, note, end time) and a "View" button; the read happens only on that click. `GET /operator/tenants/{t}/support-grants/{g}/settings` and `.../conversations/{c}`. Each call finds grant `g` in tenant `t`, of the route's scope, not revoked, not closed, before `expires_at`, and for a conversation naming `c`; anything else is 404 `not_found`, logged as `operator.support_refused` with a code only |
| (enforcement) | **Beyond the spec**, a database layer: the routes run as a new NOLOGIN role `askspore_support` with `app.tenant_id` set, column-level `SELECT` on what a user sees (no `user_id`, no `users` table), and **restrictive** `support_grant` policies on `conversations`, `messages`, `citations`, `tenant_settings`, `workspaces` and `workspace_prompts` that show rows only while an open grant covers them. A bug in the route check cannot open another conversation or tenant |
| `operator.support_viewed` with grant ID and scope, never content | Written by the support role in the same transaction as the read (no read without its event), with `operator_id`, `grant_id`, `scope` and `conversation_id`; actor `NULL` as for every operator event under a client tenant |
| The tenant admin lists grants with their state (open, used, expired, revoked) and a "revoke now" | `GET /admin/support-grants` and `POST .../{id}/revoke`. `used` means open and read at least once; reads are counted from the `operator.support_viewed` events (count and last time), not stored on the grant, so the operator never writes to it. Revoking an ended grant is 422 `not_open`. The end time is fixed at grant time; there is no extension |
| Expiry checked at read time and by the daily purge, which closes expired grants | Read time as above. The retention purge (`app.tenancy.purge`) sets `closed_at` on the tenant's expired grants and writes `support.grant_expired` per grant; `PurgeCounts.support_grants_closed`; the dry run counts them. The retention role gets the grant's state columns, `UPDATE (closed_at)` and `INSERT` on `audit_events` |
| (events) | `tenant_admin.support_granted` (grant, scope, conversation, duration), `tenant_admin.support_revoked`, `operator.support_viewed`, `support.grant_expired`, all exported to the tenant. New audit keys `grant_id`, `scope`, `duration_minutes`; new log field `grant_id`. The note is never in a log or an event |
| (personal data) | The grant row names **no user**: who granted or revoked it is in the audit events. So user removal needs no change (no user column) and termination deletes the tenant's grants with the rest (`PURGED_TABLES`) |
| A conversation grant shows question, answer text and citations as the user sees them | Messages in the user's order, citations with marker, title, publisher, date, page, excerpt and the superseded and withdrawn flags; no user identifier, conversation or message ID. Read-time expiry of the conversation applies, as for its user |
| No impersonation; no writes | The operator's own session; only `GET` routes; the support role cannot update or delete anything or read `users` (tested) |
| Tests | `test_support_access.py`, negative first: no grant; an expired grant; a grant for another conversation (the admin's other one, a member's, a random ID) and the wrong scope either way; another tenant's grant under this tenant's page (and the positive control under its own); revocation stops the next read; the database's policies on their own, as the support role (granted, other, expired, revoked, no tenant); no write and no `user_id` or `users` read; a runtime capture of stdout and the log records across a read and two refusals with none of the conversation's texts, the note, the title or the email in any line or audit row; the admin page's states and read counts, the event metadata, the export; the settings view; grant validation (own conversation only, duration bounds, note) and admin-only routes; the immutability trigger; the purge closing expired grants once. `test_logging_policy`: a static scan of `app/support/access.py` (log fields, `record` keys and raised exceptions are identifiers or constants), and field allow-lists for the grant lists and the view schemas (no user identifier). Web: grant row states and the revoke button, the read-only conversation and settings views; Playwright: the operator's tab and view |

### P2A-10 Policy and checklist documents

| Spec says | Built |
| --- | --- |
| Support-access policy text into `policy-access-control.md`, replacing rule 7's "not built" | Rule 7 rewritten; new §2.1 (who requests, what may be granted, duration, who holds it, what the operator can do, how it is checked, how the tenant sees it, review); the controls table marks it built |
| Staff onboarding and offboarding checklist | `design/compliance/staff-access-checklist.md` (confidentiality, Authentik and MFA, operator and content roles, support access briefing, SSH, RAGFlow, GitHub, Scaleway and other consoles, secrets rotation, mail and documents, devices, exit interview, record); row D22 in `paperwork-checklist.md` |
| First quarterly access review date set by the owner (H2) | Left as `[first review date]` in rule 9, which now also reviews the quarter's support reads |
| Operator MFA line to TOTP, hardware keys a Phase 2 item, unless the owner builds passkeys (D7) | Rule 4 changed and marked **proposed for the owner**; until D7 is taken the earlier hardware-key line stands. The staff checklist follows the same proposal |
| `records-of-processing` and `privacy-notice.md` note the support-access control; audit retention keeps "no disposal path yet" | Records: C4 purpose and TOMs, Part 2 sheet processing (7), retention (grants; the audit line now says "no disposal path yet", C1); privacy notice §2 and the audit row, owner note 8. The consent notice itself (`config/consent/v1.md`) is unchanged (question 1) |
| `open-questions.md` C3 and C5 answered | C3 answered (built). C5 answered as a proposal: nothing built in Phase 2A; (a) record the decision or (b) an audited console action later; recommendation (b) in the next phase touching the operator console, (a) until then. C1 left open |
| (drift) | Also updated so no document contradicts the build: `security-questionnaire.md` 5.6, `client-dpa-draft.md` owner note 7, architecture §7.2 and §7.4. Two ideas in `backlog.md` (support on a user's own conversation; the suspension action) |

### Notes for the integration

- **0065 re-parent** onto Group A's head.
- **`app/audit/events.py`** classifies Group A's `source.paused`/`source.resumed` and Group D's
  `site.reinstated` ahead. Any other new event name in Groups A, D or E fails
  `test_audit_events` (and `record()` at run time) until it is classified there.
- **`test_logging_policy.py`**: this branch appends the usage and support checks at the end;
  Group E adds the `RagflowError` scan. Keep both.
- **`AUDIT_METADATA_KEYS`** and the log `ALLOWED_FIELDS` (and `test_logging`'s copy) gain
  `grant_id`, `scope`, `duration_minutes`; Group A adds its own keys in the same lists.
- **`OperatorTenant.tsx`** gains a "Support access" tab (`TENANT_TABS`); Group A's P2A-04 adds
  a link on the workspace card in the same file.
- Regenerate `apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` after the merge.
- The ARIA snapshots of `11-tenant-admin` and `11c-tenant-admin-remove-confirm` are updated
  here. The visual baselines (`e2e/visual`, run in its image by `pnpm test:visual`) of the
  admin page and the operator tenant page will differ (new sections, column and tab) and
  were **not refreshed** here; refresh them at integration.
- `test_consent`'s export test resets the per-admin export limiter before its second call.

### Checks run (last lines, on the branch head before this section)

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | All checks passed! |
| `uv run --directory apps/api ruff format --check .` | 223 files already formatted |
| `uv run --directory apps/api mypy app` | Success: no issues found in 112 source files |
| `uv run --directory apps/api pytest` (PostgreSQL 16, `REQUIRE_DB_TESTS=1`) | 1593 passed, 1 deselected |
| `pnpm --dir apps/web lint` | All matched files use Prettier code style! |
| `pnpm --dir apps/web typecheck` | exit 0 |
| `pnpm --dir apps/web test` | Tests 177 passed (177) |
| Playwright (preinstalled Chromium, full suite) | 548 passed |

Baseline before the build: 1528 API tests and 163 web tests passed. No dependency changed.
`packages/eval` is untouched.

### Questions for the owner

1. **Which conversations can be granted.** Built: only the tenant admin's own conversations
   (or the settings). The consent notice says staff read a conversation "where your
   employer asks for support on a specific conversation", which is broader: no user's
   conversation can be shared today, so the notice stays true but promises more than the
   product offers. Recommendation: keep the narrow build for now (no admin can expose a
   user's text), and if a client asks, build the user-initiated request in the backlog;
   counsel to say whether the notice should be narrowed in its next version.
2. **Operator configuration events in the tenant's export.** Following the spec, the
   operator's changes to entitlements, login policy, SSO source, workspaces and the
   downloadable flag left the export (the old `operator.` prefix included them).
   Recommendation: export `operator.login_policy_changed`, `operator.sso_source_changed`
   and `operator.entitlements_changed`: a security contact asks who changed how their
   users sign in, and their metadata are non-secret settings by design. A one-line change
   to `EXPORTED_EVENTS` if you agree.
3. **Rate limit and continuation parts.** A period over 10,000 events is downloaded one part
   a minute. Recommendation: keep; such periods are rare and the page says to wait.
4. **Unclassified events at run time.** `record()` refuses an unclassified name, so a new
   event that slipped past the tests would fail its action (500) rather than write an
   unclassified row. Recommendation: keep (fail closed); the static scan makes it a test
   failure first.
5. **D7.** Take the TOTP line for operators (recommended: it matches what is configured and
   checkable today) and then update open question D2 ("is hardware-key MFA configured")
   to "is TOTP configured for every operator".
6. **C5.** Choose (a) record the decision or (b) build the audited suspension action;
   recommendation (b) in the next phase that touches the operator console.
7. **H2.** Set the first quarterly access review date in `policy-access-control.md` rule 9.
8. **Usage counts.** Questions per day count every `chat.query` event, refused and failed
   ones included. Recommendation: keep (it is the demand the tenant had); the alternative
   is answered questions only, a one-line filter.
