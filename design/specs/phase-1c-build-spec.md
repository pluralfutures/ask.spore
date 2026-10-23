# Phase 1c Build Spec — Hardening Before the First Client User

Oct 23, 2026 · Status: approved by the owner Oct 23, 2026 (decisions below) · Target duration: 3–4 weeks · Starts after Phase 1b closed (findings 1b §8, Oct 23, 2026)

Source decisions: the Phase 1b release record (`phase-1b-findings.md` §8, F1 to F5, the
independent review of Oct 22, 2026 and its five items), every `backlog.md` line marked
"before the first client user" or "pre-launch", the owner's request of Oct 23, 2026 for this
phase, and the owner's priorities of Oct 21, 2026 (two-host deployment stays priority 4, out
of this phase).

## Goal

Remove everything the Phase 1b release marked as needed before a client's user signs in, and
the operational gaps the release exposed, without adding product surface. Phase 1b built the
platform; Phase 1c makes it safe to hand to a client's IT department and to run without a
session at the keyboard. Everything stays on the single Instance.

Exit criteria (all must hold):

- Every Group A item is done with its tests, and the release checks of P1c-16 pass on the
  Instance with the review signed.
- A deploy from a clean `main` to the Instance is one documented script run, and it brings
  up every service the application needs (P1c-10).
- The eval set v1 result at `vector_similarity_weight = 0.4` is confirmed by a second run,
  and the three items the release could not get right (hc-v1-039, 055, 058) are either fixed
  by a new prompt version with evals or recorded as accepted with the reason (P1c-13).
- The backlog carries no line that Phase 1b already delivered (P1c-15).

The invitation of the first `customculinary.com` user is **not** an exit criterion (owner,
Oct 23, 2026). It is an operator action the owner takes when the paperwork gate (P1b-13 b,
owner-held) and this phase are both done.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- Two-host deployment, Object Storage for the content store, monitoring stack, Secret
  Manager (owner priority 4; needs a second client or a second region to justify it).
- Client-supplied documents step 2 (P1b-19), until a second client is in sight.
- Web-search mode, user-edited workspace prompts with versioning, per-model evals with
  reasoning on, source filters, trust and status pages, hardware keys for admins (Phase 2).
- Tenant self-service SSO (Phase 3). SAML stays desk-checked unless a client needs it.
- The P1a-15 paperwork gate itself and the two OpenRouter verification calls: owner-held
  (P1b-13 b). Enabling external models for `cc` is an operator action after the gate, not a
  build item.
- The no-self-approval rule in the source register (returns when a second internal user
  exists).
- Any new table, model, provider or prompt beyond P1c-13's prompt version.

## Deployment target

The Phase 1b Instance (shared 8 vCPU, 32 GB, 100 GB Block Storage) running `main` with
Compose, Caddy TLS, Authentik, RAGFlow and the worker on the Compose network. No new
service. Branch work on the Instance happens in a separate `git worktree`; the live tree
stays on `main` (Phase 1b release caveat).

## Work items

Build in this order; items in a group can be parallelised. Every change keeps the CLAUDE.md
rules and adds a test, with the negative case for every isolation control. Item IDs go in
commit messages.

### Group A — Before the first client user (priority 1)

**P1c-01 Tags: safe default and package check.** A tag with no `tenant` in `config/tags.toml`
belongs to the internal tenant; sharing with every tenant is explicit (`shared = true`).
`load_tags` refuses a file that relies on the old default. The operator API refuses a
workspace save that names a tag outside the tenant's package or the shared set (today only
the picker filters). Tests: an unset `tenant` never appears on a client picker; a tag outside
the package is refused with a code; the internal `research` workspace keeps the `sample-*`
tags. Closes backlog Oct 22 (5.1) and the Phase 1a console item.

**P1c-02 SSO refusals and audit.** An out-of-domain or unverified sign-in through a tenant's
source ends in a clear refusal on our landing page (an Authentik policy or mapping return
value, never an exception), with `auth.login_failed` carrying `method = sso:<kind>` and the
refusal code; successful logins carry `sso:<kind>` too. Removing a source clears the
console's form. Tests with the fake IdP: refusal path returns the page, no 500, no
`configuration_error` event; the audit export shows the kind. Closes backlog Oct 22 (three
lines).

**P1c-03 Credentials rotation.** A written rotation procedure in `infra/README.md` (database
roles, Authentik bootstrap token and admin password, RAGFlow, Redis if a password is set),
run once on the Instance by the owner with the session's guidance, and a startup check that
refuses to start with any password equal to an `.env.example` value. Test: the check fires on
the example values. Closes backlog Oct 22 (pre-launch).

**P1c-04 Jobs table isolation and the port test.** Row-level security on `jobs`: the
application role's policy scoped by the payload's `tenant_id`, the worker and operator roles
unscoped, with a cross-tenant zero-rows test; a test that parses the Compose files and fails
on any published port that is not loopback, except Caddy's 80 and 443; `FetchError` messages
asserted never logged in the static logging policy test; `[retention] downloads_days` capped
at 365. Closes the independent review's four items.

**P1c-05 Mail domain policy.** DMARC on the organisation domain moved to `p=quarantine`
after one week of clean reports from the platform mail (owner action at the DNS; the
session checks the reports' summary, counts only). Closes backlog Oct 22 (pre-launch).

**P1c-06 Image re-pins.** Read the publishers' changelogs for the three Docker Hub tags that
moved on Oct 21 (`postgres:16.15-alpine`, `redis:7.4.11-alpine`, `caddy:2.11.7-alpine`),
re-pin with `image-digests.py --write` in one PR, full suite on it, deploy. Closes backlog
Oct 22.

### Group B — Sign-in and onboarding polish (priority 2)

**P1c-07 Invitations and user removal.** "Resend invitation" in the operator console and the
tenant admin pages for a user still `invited` (re-queues the mail, audited); the first
invite's `email_taken` becomes a visible message; an audited "remove user" action (tenant
admin or operator) that deletes a user's account data and history as the termination purge
does for a tenant, keeping audit events. Tests: resend queues exactly one job; removal leaves
no row with the user's ID outside `audit_events`; a tenant admin cannot remove a user of
another tenant. Closes backlog Oct 22 (D5) and Oct 23 (close-out).

**P1c-08 Console feedback.** A QR code on the TOTP enrolment page; "Saved" or the error after
every console save; a link between the operator console and the chat app; terminated tenants
shown as such (slug, `suspended`, purge date, certificate number). Tests: the enrolment page
renders the `otpauth://` URI as an image and as text; a save shows a confirmation; a purged
tenant is listed with its certificate number. Closes backlog Oct 22 and Oct 23 (F5).

**P1c-09 Chat history completeness.** The truncated flag stored on `messages` (migration) so
the cut-off note survives a reload and shows in history; a "stop generation" button; the
question kept (with a flagged partial answer) when the model fails or the client disconnects
mid-stream, except for no-history tenants. Tests: a reloaded conversation shows the note; a
stopped answer is stored as partial; a no-history conversation still leaves no row. Closes
backlog Phase 1a release and P0-14, P0-16.

### Group C — Operations (priority 2)

**P1c-10 Deploy script.** `infra/scripts/deploy.sh`: pull `main` (or a named commit), run the
image-digest check, build every image including `migrate` and `web-build`, run migrations,
start RAGFlow with its embedding service, the api, worker and Caddy, set
`ASK_SPORE_DEPLOY_VERSION` from the commit, check `/healthz`, `auth/mode`, the worker's
startup lines and the dataset counts, and print a metadata-only summary. A dry-run mode for
CI (`compose config` and the digest check). Tests: the script's dry run passes in CI; the
Compose dependency from RAGFlow to its embedding service is asserted. Closes F1, F3 and the
deploy-version cache item.

**P1c-11 CI reliability.** The Playwright admin-instructions test made deterministic (find
the race, fix the wait). Branch protection on `main`: asked a third time and declined by the
owner (decision 2, Oct 23, 2026); the backlog line is closed as "owner decision: no", not
carried further. Tests: the Playwright test passes ten times in a row locally. Closes backlog
Phase 1a release (two lines).

**P1c-12 Backup restore test and eval outputs.** The owner's nightly backup restored once
into a scratch Compose project on the Instance (Postgres and RAGFlow volumes), the row and
document counts compared with the live figures, recorded in the findings; a nightly copy of
the content store (`[files] content_root`) added to the same backup; the eval harness
writes full run outputs under `/srv/ask-spore/eval-runs/` by default and only redacted
results under `packages/eval/results/`. Tests: the harness's output paths; the eval gate test
passes on a tree with full outputs present. Closes the open backup item and the release
caveat.

### Group D — Content and quality (priority 3)

**P1c-13 Eval follow-ups.** A second full eval set v1 run at weight 0.4 (confirms the Oct 23
tuning, one run per weight); then the three items the release could not get right:
hc-v1-039 (synthesis answered without a citation and withheld) and hc-v1-055, hc-v1-058
(out-of-corpus near-misses answered with citations). Try `corpus_only/v6` first (a new
version file, both evals); if wording does not move them, a relevance check of the top
passages before the answer call, as its own spec item with a design note. Accepting the
items as known limits is an owner decision recorded in the findings. Closes backlog Oct 23.

**P1c-14 Register and crawl follow-ups.** Site-level "withdraw site" in the console and CLI;
"restore" for a withdrawn crawled page; clean-up of an interrupted re-tag job; the
re-ingestion rule (decision 3: a new file replaces an existing document only when **both**
the canonical link and the title match; otherwise it is flagged to the reviewer as a
possible replacement, as decision 4 of Oct 22 already does for the link alone) and the
withdrawal excerpt rule (decision 3: the stored excerpt of a citation is **blanked on every
withdrawal**, not only on licence grounds; the citation stays, labelled withdrawn). Tests per action; a restored page is crawled again; a withdrawn
site leaves no page in any dataset. Closes backlog Oct 22 and the Group A1 follow-ups.

**P1c-15 Backlog triage.** Strike every `backlog.md` line Phase 1b delivered (the content
console, approval flow, retention jobs, SSO connectors, platform mail, the Authentik
blueprint, per-IP rate limit, session refresh and revocation, the console one-tenant layout,
the `no_binding` message, the deploy version in the cache key, the consent gate, the Phase 1
document sets), each with the item that delivered it, and re-tag the rest as Phase 1c, Phase 2
or Phase 3. One PR, no code.

### Group E — Release checks (priority 1, last)

**P1c-16 Release checks.** On the Instance, by the deploy script: the full test suite with the
database; eval set v1 and the guardrail eval against the Oct 23 baseline, no regression; the
two checks the Phase 1b release did not replay live (a refresh-token call after sign-out is
refused; a conversation request before consent is refused); one SSO refusal per kind shows
the landing-page refusal; the credentials check refuses example values; a restore test
recorded; findings file `phase-1c-findings.md` with the release record and an independent
review signed as in Phase 1b §8.2.

## Open items for the owner

- **DMARC** (P1c-05): the DNS change is the owner's; the session says when the reports are
  clean.
- **Credentials rotation** (P1c-03): the owner runs the procedure with the session's
  guidance; secrets never pass through a session.
- **Eval known limits** (P1c-13): if hc-v1-039, 055 and 058 do not move with a prompt
  version, accept them as known limits or fund the relevance-check item.
- **`cc-shared` content** (P1b-13 d): which files carry the shared tag; stays empty until
  decided. Not a Phase 1c build item.
- **Paperwork gate** (P1b-13 b): checklist items 1 to 13, counsel review of the consent notice
  (v2), privacy notice, terms and DPA, open questions A to I and J. Owner and counsel, in
  parallel with this phase.

## Owner decisions of Oct 23, 2026

| # | Decision | Applies to |
| --- | --- | --- |
| 1 | **Spec approved as drafted.** | All items |
| 2 | **No branch protection on `main` for now** (third ask). P1c-11 keeps the Playwright fix only; the backlog line closes as an owner decision. | P1c-11 |
| 3 | **Re-ingestion requires the same canonical link and the same title** to replace a document; **citation excerpts are blanked on every withdrawal.** | P1c-14 (A1-14, A1-15) |
| 4 | **Three parallel build sessions**: Group A; Groups B and C; Group D. Then integration by the orchestrating session, then the release session (Group E). | Session plan |
| 5 | **UI refresh** (visual audit and mockups, owner's prompt of Oct 23): deferred; runs after Phase 1c, not alongside it. | Out of phase |

## Owner decisions of Oct 23, 2026, second set (after the Group A and D builds)

The builders' questions (findings 1c §1 and §3); the owner took every recommendation
("yes to all").

| # | Decision | Applies to |
| --- | --- | --- |
| 6 | Compliance guide wording on platform tags updated to `shared = true`. | P1c-01 |
| 7 | Sign-in page refusal reasons stay coarse; an uninvited address and another tenant's user both read "no access". | P1c-02 |
| 8 | The credentials check runs in OIDC mode only; local Phase 0 stacks keep their development passwords. | P1c-03 |
| 9 | Credentials rotation is the **first step of the Phase 1c release**, run by the owner in their own terminal with the session's procedure, before the deploy that carries P1c-03. | P1c-03, P1c-16 |
| 10 | P1c-06 image re-pins are done from the Instance in the release step (the build container is rate-limited by Docker Hub). | P1c-06, P1c-16 |
| 11 | No migration step for pre-existing SSO sources (none exist); the release checks re-save any source present at release time. | P1c-02, P1c-16 |
| 12 | If `corpus_only/v6` fixes only some of hc-v1-039, 055 and 058 without regressing elsewhere, the rest are accepted as known limits and recorded; the relevance check stays a backlog item. | P1c-13 |
| 13 | Citation excerpts are kept when a newer version replaces a document and blanked when the document is withdrawn. | P1c-14 (e) |
| 14 | The reviewer keeps the "keep both" option on a same-link, same-title match. | P1c-14 (d) |
| 15 | A withdrawn site is final; reinstating one is a Phase 2 backlog line. Restore of a page does not queue a crawl. | P1c-14 (a, b) |
| 16 | The "licence grounds" flag stays as a record on the takedown queue. | P1c-14 (e) |
| 17 | Migration re-parenting (0042, 0050s, 0060) is done at integration by the orchestrating session. | Integration |
