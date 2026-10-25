# Phase 2 — ideas only

**Status: ideas, not a spec.** Written Oct 23, 2026 by the orchestrating session at the owner's
request, while the Phase 1c release was in progress. Nothing here is approved, sized or ordered.
The Phase 2 build spec is written only after the first client (`customculinary.com`) has used
the platform for two to four weeks and its feedback is in; that feedback decides which of these
ideas go in, which wait, and which die. Until then `backlog.md` stays the record and this file is
a reading aid for the planning conversation.

Sources: `backlog.md` (every Phase 2 line as of Oct 23), the "Not in this phase" lists of the
Phase 1a, 1b and 1c specs, architecture §11 (phasing table) and the open rows of
`design/compliance/`. Where an idea came from a release finding, the finding is named so the
planning conversation can read the evidence.

**Oct 25, 2026:** the owner chose a first cut, **Phase 2A**, from this list: item 1 (document
pause, added Oct 25 and not in the Oct 23 text), 2.4, 2.5, 2.8, 4.1 (the two static files
only), 4.2's two build items and the logging follow-up. Its spec is
`phase-2a-build-spec.md` (draft for approval). The rest of this file stays the reading aid for
what comes after.

## 0. What Phase 2 is for

Architecture §11 calls Phase 2 "Scale and assurance": web-search mode, a tenant admin
dashboard, extraction-detection tuning, provider failover drills, the trust page, and the start
of the SOC 2 observation window; exit criterion SOC 2 Type I and three or more tenants. The
build so far has already delivered parts of that line (trust page drafted, provider failover
designed but inactive) and added items the architecture did not foresee (withdrawn-site
reinstatement, per-path text-and-data-mining rules). The planning conversation should restate
the purpose in one sentence before picking items. Two candidate framings:

- **Assurance first.** Phase 2 is what SOC 2 Type I needs plus what the first client asked
  for. Everything that makes the service bigger (web search, second host, more tenants'
  features) waits for Phase 3. Fits a single operator and one client.
- **Second client first.** Phase 2 is what a second client needs to sign: client-supplied
  documents, Object Storage, self-service pieces, the trust and status pages. Assurance work is
  limited to the paperwork gate. Fits a sales pipeline that already has a name in it.

The ideas below are grouped by theme, not by framing. Each says what it is, why it was
deferred, what it touches, what has to be decided, and what would have to be true for it to
make the cut.

## 1. Answer quality and the model path

### 1.1 Web-search mode (architecture §5 step 6, §11)

What: a third answer mode in which the generation request carries Mistral's own web-search
tool, scoped to the rewritten query; web citations shown apart from corpus citations with URL
and retrieval date; answers not cached; mode enabled per tenant by the operator only, with the
DPA clause reference recorded.

Why deferred: it needs a DPA clause and new UI labelling, and the active provider is Scaleway,
not Mistral. Mistral is configured but inactive (business continuity policy §2).

Touches: `config/models.toml` allow-list (Mistral EU endpoint becomes active), the orchestrator
(tool attached only for entitled tenants; the only tool the model ever gets), the citation
mapper, the chat UI (banner, separate citation panel), operator console entitlement with a
contractual-basis field, the privacy notice and the client DPA.

Decide: whether Mistral is wanted at all as a second EU provider; the per-call price of the tool
(architecture §13 open question 1); whether a client has asked for live web answers. Without a
client ask, this is the easiest idea to drop.

### 1.2 Relevance check before answering (findings 1a §11; backlog Phase 1c fallback line)

What: either a two-step answer call (a short "does any passage answer this?" verdict, then the
answer only on yes) or a relevance check of the top passages in the orchestrator before the
LLM call. Aimed at the three eval items that no prompt version got right at any weight:
hc-v1-039 (synthesis withheld), hc-v1-055 and hc-v1-058 (out of corpus but answered with
citations).

Why deferred: P1c-13 chose one more prompt version (`corpus_only/v6`) and a design note; a
second model call per question changes latency and cost and needs its own eval design.

Touches: orchestrator, eval harness (a new metric for the verdict step), `config/prompts/`
(a verdict prompt, versioned), cost report (two calls per question).

Decide: only after the Phase 1c eval results (runbook 5.4). If v6 was adopted and the three
items moved, this idea is closed. If v5 stayed active with known limits, this is the first
answer-quality item of Phase 2.

### 1.3 Per-model eval baselines and reasoning evals (backlog, findings 1a §10 F6, F7)

What: a baseline per model (today one baseline on `deepseek-v4.1-flash`, reasoning off), plus
evals with reasoning on for Qwen at `medium`, covering answer quality, latency and the
6,000-token reasoning budget. DeepSeek reasoning is offered again only if Scaleway bounds its
length (it ran to the full output budget in 5 of 7 release runs).

Touches: `packages/eval` (baseline per model and per reasoning setting; the gate compares like
with like), `packages/eval/results/` layout, the release runbook pattern (one temporary api per
config copy).

Decide: whether Qwen stays an answering model or remains the judge only. If the client uses one
model, one baseline is enough and this waits.

### 1.4 Guardrail eval scoring (backlog, findings 1a §11)

What: score the fixed refusal and abstention sentences explicitly, in the question's language,
instead of inferring them from citations and the 40-character leak rule. Harness change only.

Decide: cheap and self-contained; a good first item for a session warming up on the eval code.

### 1.5 Tokenizer vendoring (owner decision 23, Oct 22; findings 1b E2-7)

What: replace the third-party `deepseek-tokenizer` package with DeepSeek's own
`tokenizer.json` under `tokenizers`, once someone with Hugging Face access has compared the
two files. Token counts feed the cost report and the reasoning budget.

Decide: needs a person with the access, about an hour. Not a session item until the comparison
is done.

## 2. Workspaces, content and the tenant's view

### 2.1 User-edited workspace prompts with versioning (architecture §7, backlog)

What: any tenant user may edit a workspace's additional-instructions block; every edit
versioned with author and time, audited, revertible by the tenant admin. Phase 1a allows tenant
admins only.

Touches: a `workspace_prompt_versions` table (tenant-scoped, RLS, tenant-first index), the
tenant-name match flag per version (operator-only, never shown to the tenant), the workspace
page, audit events, the tenant admin's revert action.

Decide: whether the client wants its analysts editing prompts at all. Many clients would rather
the admin keep that control. Ask them before building.

### 2.2 Source filters from the per-workspace file list (architecture §7.1, backlog)

What: P1a-09 is a plain list; the idea is search and filters (publisher, year, tag, type) and
an answer-time filter so a user can ask "only from these sources". The retrieval call stays
server-built: a filter is a selection within the tenant's package, never a dataset or document
ID from the client.

Touches: file list API and UI, the orchestrator's retrieval call (a filter expression resolved
server-side to RAGFlow document IDs), cache key (filter becomes part of the key), eval (a
filtered-question set).

Decide: the first real client ask of this kind decides the shape. Build nothing speculative.

### 2.3 Client-supplied documents, step 2 (P1b-19; architecture §15 design)

What: tenants upload their own documents into a tenant-private dataset, parsed and indexed by
RAGFlow, retrievable only within that tenant's package, exportable and deleted on termination
with the certificate. Step 1 (the design, DPA wording, offboarding pack) exists; step 2 is the
build.

Why deferred: "until a second client is in sight" (Phase 1c spec). It changes the compliance
position from public-sources-only to processing client confidential documents.

Touches: upload path with virus scanning, a per-tenant RAGFlow dataset created server-side,
the content store (Object Storage, 3.1), termination purge, the DPA (clause 10.5 already
drafted), the DPIA, the records of processing, the security questionnaire.

Decide: this is the largest item on the list and the one most likely to sell a second client.
It is a phase of its own if chosen; do not put it in a Phase 2 with much else.

### 2.4 Tenant admin dashboard and audit-log download (architecture §7.2, §11)

What: a tenant admin page with usage counts (questions per day, active users, cost per model
where the tenant pays), consent status per user, retention setting, and a download of the
tenant's own audit events as CSV. The download leaves out operator-only events
(`workspace.prompt_tenant_name_match`).

Touches: an aggregation query per tenant (RLS does the scoping), a CSV export job through the
worker, the tenant admin UI, a new audit event for the export itself.

Decide: likely wanted by any client's security contact at renewal time. Medium size.

### 2.5 Withdrawn-site reinstatement (P1c-14 build, backlog)

What: a withdrawn site is final and keeps its unique start URL, so it cannot be registered
again. A "reinstate" action (back to `proposed` for a reviewer) or a release of the start URL,
for the case where a publisher lifts its objection.

Decide: small; wait until it happens once.

### 2.6 Takedown licence flag (P1c-14 (e), owner decision 3)

What: `sources.takedown_licence_grounds` no longer changes behaviour since every withdrawal
blanks excerpts. Keep it as a record on the takedown queue, or drop the flag and its checkbox.

Decide: a one-line owner decision at planning; either outcome is an hour of work.

### 2.7 Per-path text-and-data-mining rules and site terms review (P0-10 carry-over)

What: today any reservation in a site's `tdmrep.json` blocks the whole site. Per-path rules
would allow the unreserved paths; a site terms review step would record that a human read the
site's terms before the first crawl.

Touches: the crawler policy module, the site register (a terms-reviewed field and reviewer),
the crawl drill in the release runbook.

Decide: matters when the corpus grows past the owner's own sites. Low urgency.

### 2.8 Public holidays in takedown due dates (findings 1b A1-17)

What: a configurable calendar so the 10-working-day takedown clock skips public holidays;
Phase 1b counts Monday to Friday only. Small.

### 2.9 No-self-approval in the source register (P1b-01, owner decision Oct 21)

What: a reviewer cannot approve their own proposal. Returns when a second internal user exists.
Until then self-approval is allowed and audited. Not a Phase 2 item unless a second internal
user is hired.

## 3. Platform, deployment and operations

### 3.1 Two-host deployment, Object Storage, monitoring, Secret Manager (owner priority 4)

What: the single Instance becomes two (application host and data host, or application and
RAGFlow), the download content store moves to Scaleway Object Storage in Paris with backup
(`app.content.store` is the only module that changes; the API reads by `stored_path`), a
monitoring stack (metrics, alerts, uptime), and Scaleway Secret Manager in place of `.env`
files.

Why deferred: "needs a second client or a second region to justify it" (Phase 1c spec). One
client on one Instance is within the business continuity policy's stated posture.

Touches: Compose split, Caddy, the deploy script (two targets), backups (the content store
leaves the volume backup), the credentials procedure (Secret Manager changes rotation),
`infra/README.md`, the business continuity policy, the restore test.

Decide: pick the trigger explicitly: second client signed, or a month of client usage with an
incident, or an RTO the single host cannot meet. Monitoring alone could be pulled forward (see
Ongoing Operations, "Observability"), since today nothing alerts anyone.

### 3.2 RAGFlow web UI production path (findings R3, A2-18)

What: RAGFlow's UI and nginx (which also proxies RAGFlow's API) are on loopback only, reached
over an SSH tunnel. The open choice is an authenticating proxy (Caddy with Authentik forward
auth on an internal hostname) or keeping the tunnel for good.

Decide: a one-session item if the proxy is chosen; the tunnel is acceptable while the owner is
the only content editor.

### 3.3 Provider failover drills (architecture §11; business continuity §3.5)

What: there is no automatic provider failover; the operator changes the workspace default
model or the `[llm] provider` setting by hand. A drill would time that change end to end and
record it. OpenRouter EU as a backup inference provider waits for the paperwork gate.

Decide: a half-day drill, not a build item; belongs in the operations calendar once a quarter.

### 3.4 Hardware keys or passkeys for admins (owner decision Oct 22; findings B15)

What: WebAuthn as the admin second factor instead of TOTP. Needs a browser-run Authentik flow
or a WebAuthn relay in the API, because the API-run sign-in flow cannot relay WebAuthn.

Decide: the access-control policy says operator accounts use hardware-key MFA; today the
operator uses TOTP too. SOC 2 does not require hardware keys, but the policy should match the
build. Either build this or soften the policy line at planning.

### 3.5 Invitation resend rate limit (B/C review, Oct 23; P1c-07)

What: refuse a resend within a few minutes of the last `send_mail` for that user, so a tenant
admin cannot flood an address. Listed as "before the first client user" in the backlog, so it
is strictly a Phase 1c follow-up, not Phase 2; recorded here so it is not forgotten if the
release closes without it.

## 4. Public pages, assurance and paperwork

### 4.1 Trust, status and public pages (backlog Oct 19)

What: trust page (drafted, waits on paperwork item 4), status page with an SLA statement, help
centre and model/mode explainer, package coverage page, changelog with model-change notices,
cookie notice, `security.txt` and a responsible disclosure page.

Touches: the public site (outside the application, separate privacy notice), a status source
(a monitoring stack or a third-party status page), the changelog process in change
management.

Decide: the trust page and `security.txt` are due before launch regardless; the rest is a
marketing and support question for the owner. None of it needs a coding session except the
status page's data source.

### 4.2 SOC 2 observation window preparation

What: the compliance guide lists the items due before the window opens: the support-access
policy (time-boxed, logged support access is described in the consent notice but not built),
the staff onboarding and offboarding checklist, the quarterly access review with its first
date, HR answers (background checks, training, insurance), log retention fixed to a number,
audit disposal (open question C1: events are promised for 12 months but nothing can delete
them), the bespoke OpenRouter ZDR confirmation and fuller TIA.

Touches: mostly documents under `design/compliance/`; two build items hide inside: the
support-access feature (an operator action with a time box, a reason, an audit event and a
tenant-visible record) and a controlled audit disposal job (a role that may delete audit
events older than the retention, with its own certificate line).

Decide: whether SOC 2 Type I is a goal for the next twelve months. If yes, this group is the
backbone of Phase 2 and an auditor should be chosen before the spec is written. If no, only
the support-access and audit-disposal builds matter, because the consent notice promises both.

### 4.3 External models for the first client (paperwork gate, owner-held)

What: not a build item. Thirteen checklist rows, two done; enabling the entitlement in the
console is an operator action afterwards. Recorded here so the planning conversation can ask
the client whether they want Claude or GPT at all before any of the rows are worked.

## 5. Not Phase 2 (Phase 3 by the architecture)

Shared conversations, briefs, alerts, tenant self-service SSO, a tenant API. SAML stays
desk-checked unless a client needs it. Listed so nobody pulls them forward by accident.

## 6. How the planning conversation should run

1. Owner states the framing (§0) in one sentence and the time horizon.
2. Owner brings the client's feedback as a list of asks, each marked must, nice, or no.
3. For every idea above, one of: in, later, drop. "In" needs a reason that is either a client
   ask, a compliance promise already made (consent notice, DPA, policy), or an operational
   failure that happened.
4. The orchestrating session then writes `phase-2-build-spec.md` in the Phase 1c format:
   items with IDs (`P2-01`...), groups that can run in parallel, a "Not in this phase" list,
   decision table, exit criteria, deployment target. Size: three groups and one release
   session has worked twice; a fourth group has not been tried.
5. The spec is reviewed as the 1c spec was (owner approval of the draft, decisions recorded),
   then built, integrated, independently reviewed and released on the same pattern.
