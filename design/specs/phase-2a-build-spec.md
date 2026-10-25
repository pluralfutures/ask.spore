# Phase 2A Build Spec — Document Pause, Tenant Assurance, Promises Kept

Oct 25, 2026 · Status: **Group A approved** (owner go-ahead of Oct 25, 2026: D1 to D4 taken; D5 withdrawn;
D6 and D7 still proposed; Groups B to F await approval) · Target duration: 3–4 weeks · Starts after the UX refresh closed (UX-24, Oct 25, 2026)

Source decisions: the owner's selection of Oct 25, 2026 from `Phase 2 spec - ideas only.md`
(items 1, 2.4, 2.5, 2.8, 4.1, 4.2 and the logging follow-up of the Phase 1c independent
review), architecture §6.1, §6.3, §7.2, §7.4 and §11, the compliance guide ("Audit logging",
"Support access time-boxed and logged"), `design/compliance/open-questions.md` rows C1, C3
and C5, and `policy-data-retention-disposal.md` §4.

## Goal

Give the content team a way to take a document out of retrieval without destroying it, give
the tenant admin the usage and audit view a client's security contact asks for, and build what
the consent notice already promises but the system does not do: time-boxed support access.
Audit disposal (open question C1) moved to the backlog's "Enterprise requirements" by owner
decision of Oct 25, 2026; it stays a promise in the documents with no mechanism yet. Everything else in this phase is small and
closes a known gap. No new tenant feature beyond the admin page, no new provider, no change to
what the language model sees, no change to the content model (platform-gathered only).

Exit criteria (all must hold):

- A reviewer can pause and resume an ingested source from the content console and the CLI;
  while paused, no tenant retrieves, lists or downloads it, its RAGFlow document is left in
  place, and resuming needs no re-parse (Group A, with the negative tests).
- A tenant admin sees usage counts and consent status on the admin page and the audit export
  carries only allow-listed event names (Group B).
- Support access exists as a tenant-admin-granted, time-boxed, audited operator action that
  the tenant can see (Group C). `open-questions.md` rows C3 and C5 are answered.
- Group D and E items are done with their tests, and the release checks of P2A-13 pass on the
  Instance with an independent review signed as in Phase 1c §5.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- **Per-workspace document exclusion** (a document on in one workspace and off in another).
  Pause is corpus-wide (D1). A per-workspace selection is the source-filter item (ideas 2.2)
  and waits for a client ask.
- Source filters and search on the workspace file list (2.2); client-supplied documents step
  2 (2.3); web-search mode (1.1); the relevance check (1.2); per-model eval baselines (1.3);
  user-edited workspace prompts (2.1); two-host deployment, Object Storage, Secret Manager
  (3.1); hardware keys or passkeys (3.4, see D7); the RAGFlow UI proxy (3.2).
- A monitoring stack. A status page needs one or a third-party service; this phase decides
  the source (D6) and builds nothing for it.
- Help centre, model and mode explainer, package coverage page, changelog, cookie notice: the
  owner's documents on the public site, no coding item. The trust page is published by the
  owner once paperwork item 4 clears; this phase only serves the file.
- A tenant-side "pause" or "withdraw" action, a tenant-side upload, and any dataset or document
  ID accepted from a request.
- Any change to prompts, `config/models.toml`, the retrieval call's shape, or chat-history
  retention.
- **Audit disposal** (open question C1): backlog, "Enterprise requirements" (owner, Oct 25,
  2026). The append-only trigger stays as it is; the 12-month line in the policy and the DPA
  keeps its "no disposal path today" note until that item is built.

## Deployment target

The Phase 1c Instance (single host, Compose, Caddy TLS, Authentik, RAGFlow `v0.27.2`, the
worker) running `main`. No new service. One new Compose-level change: Caddy serves two static
files (P2A-11). Migrations: one for the `paused` status and its columns, one for support-access
grants.

## Work items

Build in this order; items in a group can be parallelised. Every change keeps the CLAUDE.md
rules and adds a test, with the negative case for every isolation control. Item IDs go in
commit messages.

### Group A — Document pause (priority 1, critical)

**P2A-00 RAGFlow probe — done Oct 25, 2026** (`phase-2a-findings.md`, "P2A-00 probe").
RAGFlow `v0.27.2` has the toggle on `/api/v1`, so **mechanism (a) is taken** (D2). The call
is `PATCH /api/v1/datasets/<dataset_id>/documents/<document_id>` with `{"enabled": 0}` to
pause and `{"enabled": 1}` to resume; `enabled` is an integer (a boolean is refused, code
102), a `status` field is silently ignored, and the success envelope's `data.status` ("0" or
"1") is the confirmation to check. Retrieval excluded the paused document from the first
call after the toggle and returned it from the first call after resuming; no re-parse
(document id, chunk count, token count, run state and parse timestamps unchanged). Cost: about
1 s for a 1,128-chunk document, about 90 ms for a small one, paid once per pause or resume;
the retrieval request and its latency are unchanged. **The toggle is per RAGFlow document,
and a document belongs to one dataset**: a source tagged into two datasets has two document
ids and needs one `PATCH` per entry of `ragflow_document_ids`. The response carries the file
name and storage location, so the client logs only the code, the returned status and the
latency. The chunk-list endpoint is not a reliable check (it listed 1,079 of 1,128 chunks
before and after the probe); verify a pause by `data.status` and, at release, by retrieval.

**P2A-01 Register: `paused` status.** Migration: `paused` added to `SOURCE_STATUSES`;
`paused_at`, `paused_by`, `pause_reason` (required, like a withdrawal reason) with a check
constraint that they are set if and only if the status is `paused`; a `resumed_at` is not
stored, the audit trail carries it. Transitions: `ingested → paused` and `paused → ingested`
only, by a content **reviewer** (the role that approves and withdraws), each audited
(`source.paused`, `source.resumed`, with reason, reviewer and the RAGFlow outcome). `paused →
withdrawn` is allowed through the existing withdrawal request, so a takedown on a paused
document runs the full cascade; **a pause never satisfies a takedown** (the takedown queue
shows the paused state but its due date and cascade are unchanged). The RAGFlow toggle is
made inside the register action, not in a worker job: `RagflowClient.set_document_enabled`
(`PATCH`, integer `enabled`, result read from `data.status`) once per entry of
`ragflow_document_ids`, idempotent (RAGFlow no-ops when the status already matches). If any
call fails or returns the wrong status, the action re-enables the entries it already paused
and leaves the row `ingested` with the error code returned to the console (no partial
state); `datasets sync` reports a document whose RAGFlow status disagrees with the register. The corpus fingerprint (`resolve_package`)
already includes status, so every answer-cache key of every workspace holding the source
changes on pause and on resume; the old entries age out, and `purge_answer_cache` is run on
pause as well so a cached answer never cites a paused source. Tests: pause then retrieve
through a workspace that holds the tag returns no chunk of the source (fake RAGFlow honours
the status); resume returns them again with no `start_parse` call; a failed toggle on the
second of two datasets re-enables the first and leaves the row `ingested` with no audit
event of success; a boolean `enabled` or a `status` field is never sent (asserted on the fake's
received payload); the cache key differs before and after;
a non-reviewer is refused; `paused → approved` and `proposed → paused` are refused.

**P2A-02 Pause in every tenant-facing surface.** The file list and download routes filter
on `status = 'ingested'` today, so a paused source disappears from the workspace library and
cannot be downloaded (404, as for a source outside the workspace). The provenance lookup
(`provenance_by_document`) excludes only `withdrawn`; it must exclude `paused` too, so that
`select_context` drops a paused source's chunk even if RAGFlow returned one (a chunk without
provenance never reaches the prompt). This item makes that change, adds the tests that prove
each surface, and covers the remaining one: a stored citation of a paused source keeps its excerpt and provenance
(a pause is not a withdrawal; D3) and is labelled "currently unavailable" in the chat
history, with "View at source" kept where the canonical link exists; the label disappears
on resume. Sites: the per-site page count on the library page counts ingested pages only.
Tests: the list omits the paused file for a tenant whose workspace holds the tag and still
shows the tenant's other files; the download link for a paused source is refused and
audited `download.refused`; the history view shows the label for a paused source and not
after resume; the prompt built for a question never contains a paused source's chunk even
when the fake retriever returns one (`select_context` drops chunks whose provenance is
missing, which a paused source now is).

**P2A-03 Pause and the content pipeline.** The crawler treats a paused page as held: a
changed version of a paused page is admitted as a new `approved` row that supersedes it, as
for an ingested page, and the new version is ingested **paused** (the pause is inherited,
so a recrawl cannot silently resume a document); a reviewer resumes it explicitly. Manual
re-ingestion of a paused source (same link, same title) likewise produces a paused
replacement. Re-tagging a paused source is refused with a code (`paused`); the reviewer
resumes first. Tests: a changed paused page yields a paused successor and no retrievable
chunk; a re-tag of a paused source is refused; `withdraw_source` on a paused source runs the
full cascade and blanks excerpts.

**P2A-04 Console, CLI and the tenant-facing path.** Content console: "Pause" and "Resume" on
the source detail with a reason field, a `paused` filter and badge on the source list, the
pause shown in the history timeline; the operator console's workspace card links to the
source list filtered by the workspace's tags, so an operator looking at a tenant's workspace
reaches the files it holds (the action itself stays a reviewer action; D4). CLI:
`sources pause <id> --reason` and `sources resume <id>`, the same code path. Playwright: pause
from the console, the file gone from the tenant's library, resume, the file back.

### Group B — Tenant admin dashboard (priority 2)

**P2A-05 Usage section.** A "Usage" section on the tenant admin page (architecture §7.2):
questions per day for the last 30 days by answer mode, active users per day (distinct users
with a `chat.query` event), top ten cited sources by title and publisher over the period, and,
for a tenant with the external-models entitlement, month-to-date cost per model from
`usage_ledger` (the figures the operator already sees). One aggregation route per tenant,
built from `audit_events` and `citations` under the tenant-scoped session (RLS does the
scoping), counts only; no query text, no per-user ranking, no conversation IDs in the
response. Tests: the route returns zero rows for a tenant with no events and never a row of
another tenant (two tenants seeded, each sees its own counts); the response schema has no
field that could carry a body (asserted against the schema, as `test_logging_policy` asserts
log fields).

**P2A-06 Consent status per user.** `consent_version` and whether it is the active notice
version on each row of the admin users table (`AdminUserOut` gains `consent_version` and
`consent_current`), with the notice version named in the section heading. Tests: a user who
accepted an older notice shows `consent_current = false`; the field is absent from the
non-admin `/me` body.

**P2A-07 Audit export hardening.** The export route exists (`/api/v1/admin/audit-log`, CSV,
audited as `tenant_admin.audit_exported`, 90 days by default, 10,000 rows). This item changes
the filter from prefix patterns to an **explicit allow-list of event names**, so a new
operator-only event is never exported by default (`workspace.prompt_tenant_name_match`,
`model.fallback` and every `operator.` event that is not about this tenant's users stay out;
the allow-list is a constant beside the event catalogue and a test fails when an event name
is added to the code without being classified exported or operator-only), adds `until` beside
`since`, pages the export in date windows when a window exceeds the row cap (the response
says so instead of truncating silently), rate-limits the route (one export per minute per
admin, with the limiter of `app.auth.ratelimit`), and shows the "Download" with its date fields on the
admin page's Audit section. Tests: the operator-only events never appear with every event
type seeded; an unclassified event name fails the catalogue test; the rate limit refuses the
second call; the tenant-admin page's download hits the route with the chosen dates.

### Group C — Promises already made (priority 2)

**P2A-08 Time-boxed support access.** What the consent notice (v1 §1 and §7), the
architecture (§7.4) and `policy-access-control.md` rule 7 promise: operators do not read
tenant content unless the tenant asks for support, and such access is time-boxed, logged and
visible to the tenant. Build: a `support_grants` table (tenant-scoped, RLS, `tenant_id`-first
index): granted by a **tenant admin** in the admin page, naming a scope (`settings` or one
conversation by ID chosen from their own list), a duration (15 minutes to 4 hours, default
1 hour), and a note; the operator sees open grants for a tenant on its console page and reads
the granted scope through dedicated operator routes that check the grant's scope and expiry on
every call (`operator.support_viewed`, with grant ID and scope, never content); the tenant
admin page lists grants with their state (open, used, expired, revoked) and a "revoke now";
expiry is checked at read time and by the daily purge job, which closes expired grants. The
operator never writes through a grant and never sees another conversation; a grant for a
conversation shows the question and answer text and citations as the user sees them, nothing
of other conversations. No impersonation: the operator's own session and identity are used.
Tests (negative first): an operator route without a grant, with an expired grant, with a
grant for another conversation, or with a grant of another tenant, returns 404; a revoked
grant stops the next read; nothing of the viewed conversation reaches the log (static scan and
a runtime log capture); the tenant admin page shows the view event; `support_grants` has RLS
and the index (the migration test).

**P2A-09 (moved).** Audit disposal left this phase for the backlog's "Enterprise
requirements" (owner, Oct 25, 2026). The number is kept so the Phase 2 ideas file and this
spec's drafts still line up.

**P2A-10 Policy and checklist documents.** Documents only, under `design/compliance/`: the
support-access policy text (how a grant is requested, who may hold one, the maximum duration,
how the tenant sees it) into `policy-access-control.md`, replacing rule 7's "not built"; a
staff onboarding and offboarding checklist (accounts, keys, MFA, repository, vendor consoles,
the exit interview line); the first quarterly access review date set by the owner (H2); the
access-control policy's operator MFA line changed to match the build (TOTP today, hardware
keys as a Phase 2 item) unless the owner builds passkeys instead (D7); `records-of-processing`
and `privacy-notice.md` note the support-access control; their audit-retention lines keep the
"no disposal path yet" note.
`open-questions.md` C3 and C5 answered (C5: suspension stays an operator-console action out of
this phase; record the decision or build the audited action, owner's call, an hour either way).

### Group D — Small content items and public files (priority 3)

**P2A-11 Public files.** Caddy serves `/.well-known/security.txt` (RFC 9116: contact, expiry,
preferred languages, the disclosure page URL, signed if the owner holds a key) and
`/security-disclosure` (the responsible-disclosure page, drafted under `design/compliance/`
and rendered as static HTML in the web build), both outside the application and its consent
gate; the trust page gets a route the same way and is **not published** until the owner
clears paperwork item 4 (the file stays a draft; the route 404s until the owner flips a
config flag at deploy). The status page's data source is decided (D6) and recorded; nothing
built for it. Tests: the Compose port test still passes; a Playwright check that the two
files are served without sign-in and without a consent redirect; `security.txt` parses and its
`Expires` is within a year.

**P2A-12 Withdrawn-site reinstatement (2.5) and public holidays (2.8).** (a) A reviewer
"reinstates" a withdrawn site: status back to `proposed` with a required note and
`site.reinstated` audited; the start URL is unchanged (it stays unique), the site needs a
fresh approval, its withdrawn pages stay withdrawn and the crawl's block list keeps every page
blocked for a takedown; other withdrawn pages of the site are released so the next crawl
admits them as new rows. Tests: a reinstated site is proposed, not approved; a takedown-blocked
URL is still refused by the crawl; a plainly withdrawn URL is admitted as new. (b)
`config/holidays.toml`: a calendar of dates per named region with one region marked
active in the same file, consulted by `working_days_after` so the takedown clock skips them; the
file is validated at startup like `models.toml` (no network, no library); an empty calendar
keeps today's Monday-to-Friday rule. Tests: a request on the day before a listed holiday is
due one working day later than today's rule; a malformed date refuses startup.

### Group E — Hardening follow-ups (priority 3)

**P2A-13 Logging policy follow-up.** From the Phase 1c independent review (item 3):
`IngestResult.error` and `_Failure` messages embed `str(RagflowError)`, whose detail is
RAGFlow's own message text, today reaching the CLI exit text and the source row's `error`
(shown in the console detail). Keep the error **code** only in both; the detail is dropped,
not logged. Add `RagflowError` to the handlers the static scan in `test_logging_policy`
checks, as `FetchError` and `IngestError` are. Tests: the scan rejects a handler that passes
`str(exc)` of a `RagflowError` to a log, a message or an exit; the source row's `error` after
a parse failure is a code.

### Group F — Release checks (priority 1, last)

**P2A-14 Release checks.** On the Instance, by the deploy script: migrations; the full suite
with the database; eval set v1 and the guardrail eval against the Phase 1c baseline (no prompt
changed, so no regression expected; the run proves the retrieval path still works with the
toggle in place); the pause drill live on the internal tenant (pause a `sample-*` source, ask a
question that cited it before, see no citation and no cache hit, resume, see it cited again,
each step's audit event present); a support grant opened and read on the internal tenant and
the tenant-side record checked; the two public files fetched without sign-in; findings file `phase-2a-findings.md` and an independent
review signed as in Phase 1c §5.2.

## Decisions proposed for the owner

| # | Proposal | Alternative | Applies to |
| --- | --- | --- | --- |
| D1 | **Taken, Oct 25, 2026 (go-ahead for Group A). Pause is corpus-wide.** A paused source leaves retrieval and the library of every workspace of every tenant that holds its tag, because a tag is one RAGFlow dataset shared across tenants. | Per-workspace exclusion: a server-built document-ID exclusion per workspace. Larger, overlaps 2.2, and RAGFlow's toggle cannot do it. Not recommended now. | Group A |
| D2 | **Taken, Oct 25, 2026: mechanism (a), RAGFlow's document status toggle** (`PATCH …/documents/<id>`, integer `enabled`), confirmed by the P2A-00 probe. | (b) a server-built document-ID exclusion list on the retrieval call; not needed. | P2A-00, P2A-01 |
| D3 | **Taken, Oct 25, 2026. A pause keeps stored excerpts.** Citations of a paused source stay readable in history, labelled "currently unavailable". Only a withdrawal blanks (owner decision 3, Oct 23). | Blank on pause too. Rejected: a pause is reversible and not a rights event. | P2A-02 |
| D4 | **Taken, Oct 25, 2026. Pause is a content reviewer action**, as withdrawal is; the operator console links to it. | An operator action on the tenant page. Rejected: it would be the first content decision made from a tenant's page and would blur the register's roles. | P2A-04 |
| D5 | *(withdrawn)* Audit disposal moved to the backlog, "Enterprise requirements" (owner, Oct 25, 2026); its design proposal is recorded there. | — | P2A-09 |
| D6 | **Status page source: a third-party status page** fed by hand until a monitoring stack exists (3.1); it receives no personal data unless subscribers are enabled, which stays off. Recorded, not built. | A self-hosted status page from a monitoring stack, with 3.1. | P2A-11 |
| D7 | **Soften the operator MFA policy line to TOTP** with hardware keys as a Phase 2 item. | Build passkeys now (3.4): a browser-run Authentik flow or a WebAuthn relay; a session on its own. | P2A-10 |

## Open items for the owner

- **Scope of pause** (D1): taken as corpus-wide with the Group A go-ahead. Note from the
  probe: every `sample-reports` source is also in a client dataset, so pausing one pauses it
  for that client too.
- **Chunk count gap** seen in the probe: `bugs-to-investigate.md` B-1; not a Phase 2A item.
- **Support access scope** (P2A-08): confirm that a tenant admin may grant a view of one
  conversation, as the consent notice says, or limit grants to settings only until counsel
  reviews the notice wording.
- **Holiday region** (P2A-12 b): which calendar the takedown clock follows (the operator's
  jurisdiction, stated in the terms).
- **`security.txt` contact and disclosure terms** (P2A-11): the contact address, whether a
  PGP key is published, and the safe-harbour wording for the disclosure page.
- **Candidates the owner may add**, small and from the same review: the Compose port test's
  file list (`infra/drills/keycloak/compose.yml`), and the credentials check's
  case-insensitive comparison with a minimum length. Not in the phase unless added here.

## Session plan (proposed, as in Phase 1c decision 4)

Three parallel build sessions: Group A (after P2A-00's half-day probe, which the orchestrating
session runs first); Groups B and C; Groups D and E. Then integration by the orchestrating
session, then the release session (Group F).
