# Phase 1b release runbook (P1b-16, "Group F")

Brief for the session that releases Phase 1b on the Instance. Written Oct 22, 2026 by the
orchestrating session after PR #50 (Groups E1 and E2) merged into `main`. Read `CLAUDE.md`,
the Phase 1b build spec, `phase-1b-findings.md` (sections 1 to 7) and the Phase 1a release
runbook and record (`phase-1a-findings.md` §10) first. This runbook adds nothing to the spec;
it orders the release work and fixes the values.

## Ground rules

Same as the Phase 1a runbook, restated:

- Run on the Instance from `/root/ask.spore` on `main`. Repository changes go on branch
  `phase-1b/release`, pushed for the owner to merge, then pulled before use. Never push to
  `main`. Never open a PR.
- Metadata-only output. Never print a value from `.env`, `infra/authentik/.env` or an eval
  key file, a token, a sign-in link, a client secret, a document's contents, a query or an
  answer. Report key names, counts, status codes, file names and timings.
- No wildcard or recursive deletes. Do not remove volumes, the ingestion logs under
  `/srv/ingest-out/`, or any container the runbook does not name.
- Owner decisions arrive in this brief or in a later message quoting the owner. Anything
  else that needs a decision: stop that item, report the question, continue with the rest.
- The CLAUDE.md non-negotiables are release blockers.
- The release image is built from `main`; a fix goes to `phase-1b/release`, is merged by the
  owner, pulled, rebuilt, and the affected check is re-run. Record every fix as an F-row in
  findings section 8.

## Fixed values

| Item | Value |
| --- | --- |
| Public host | `askspore.myceliumgastronomy.com` |
| Product name shown to users | SporeBot (decision 1) |
| Platform mail | Scaleway Transactional Email HTTP API, fr-par; from `reply@askspore.myceliumgastronomy.com` (decision 13); `SCALEWAY_TEM_API_KEY` is in the root `.env` (owner, Oct 22) |
| Operator | `daniel@myceliumgastronomy.com` |
| Client tenant | `cc` (CustomCulinary), verified domains `customculinary.com`, `myceliumgastronomy.com`; external models **off** (P1a-15 gate still open) |
| Test tenant for SSO | slug `ssotest`, display name "SSO test", verified domain the owner names per connector (below); deleted with the termination purge at the end (that is also the purge drill) |
| Eval service identity | `eval-service@myceliumgastronomy.com`, internal tenant; key pair under `/srv/ask-spore/eval-keys` (root only, never committed) |
| Downloads retention | 90 days (`[retention] downloads_days`) |
| Consent notice | `config/consent/v1.md` with the owner's final wording (owner input 1 below). The gate does not go live with the placeholder. |
| Eval baseline | `packages/eval/results/BASELINE` (Phase 0 run, Phase 1a gate reference); regression threshold 3 points |

## Owner inputs needed before the session starts

The orchestrating session collects these and puts them in the opening message. Items
marked "default" run with the stated value unless the owner says otherwise.

1. **Consent notice wording**: done Oct 22, 2026. The owner accepted the privacy-notice
   draft for the test phase with the company facts filled in (entity, address, DPO Daniel
   Riveong, contact address); `config/consent/v1.md` is released, pending counsel review,
   which will be v2.
2. **Eval harness under the gate**: default, the service identity is exempt (findings §7 I-2).
3. **Audit export scope**: default, add `download` events to the tenant admin export (a
   small change on `phase-1b/release`, with a test).
4. **Notice emails only to users who accepted an earlier version**: default, as built.
5. **No-history tenants**: default, as built (no context between questions, no caching).
6. **Usage ledger kept on termination**: default, keep.
7. **Judge model**: default, `qwen3.8-27b` on Scaleway as `[eval] judge_model`.
8. **Tokenizer package**: default, keep `deepseek-tokenizer` 0.3.0; vendoring goes to the backlog.
9. **SSO test identity providers** (owner, Oct 22, 2026):
   - **Entra ID**: trial tenant `myceliumtest001.onmicrosoft.com`; the test user is on that
     domain. Admin-group mapping not tested unless the owner adds a group.
   - **Google Workspace**: domain `pluralfutures.com` (owner, Oct 22, 2026), verified for
     `ssotest`; the test user is on it. A Workspace user on `myceliumgastronomy.com` is the
     unverified-domain case: that domain is verified for `cc`, so the refusal also proves
     that a Google sign-in never lands in another tenant. No change to `cc`.
   - **Generic OIDC**: the owner has no provider; use a **throwaway Keycloak** on the
     Instance as the IdP, on the test host `idp-test.askspore.myceliumgastronomy.com`
     (owner adds the A record to the Instance's IPv4; Caddy issues the certificate). A
     drill-only compose file under `infra/drills/` with a digest-pinned Keycloak image,
     a realm with one confidential client and two users (one on a domain verified for
     `ssotest`, one not), removed after the drill with its volume. SAML is then
     desk-checked only and recorded as such; Keycloak can serve SAML too if time allows.
   Client IDs and secrets are entered by the owner in the operator console, never
   pasted to a session.
10. **Backups**: whether the nightly volume backup is in place (owner-handled); the restore
    test is recorded if the owner has done it, otherwise marked open.

## Order of work

### 0. Bring the Instance up on the release image

1. Owner powers the Instance on. Open a remote-control session there; the orchestrating
   session cannot message it (trusted-device rule), so the owner relays.
2. `git -C /root/ask.spore pull` on `main`; note the commit. Confirm `.env` and
   `infra/authentik/.env` carry every key the compose files reference (names only).
3. `python3 infra/scripts/image-digests.py --check` **without** `--hub-mirror`. Any moved
   tag is a stop: report it, do not `--write`.
4. Authentik blueprint (P1b-08, README "Blueprint"): dry run in a one-off worker container,
   then `--profile auth up -d`, then `verify_blueprint.py` through `ak shell`. Record what the
   blueprint adopted and what it changed on the live instance (names only). If the
   provisioner now exists twice, keep both until step 2.5 below.
5. Build and start: `docker compose -f infra/compose.dev.yml build api web-build worker`,
   `up -d migrate` (head must be **0041**), `up -d api worker caddy`. `/healthz` 200 over
   TLS. Confirm `/api/v1/auth/mode` is `oidc`.
6. Content roles: grant the operator `content_editor` and `content_reviewer`
   (`ask-spore content-roles grant`, as schema owner). Audit events recorded.

### 1. Isolation tests and the independent review (P1b-16)

1. Full `pytest` with the database tests on the release image (`TEST_ADMIN_DATABASE_URL`
   against the Instance's Postgres in a throwaway database, never the live one; or the
   compose `postgres` service with a scratch database). Expected: everything passes (1345
   at commit 4389218).
2. List the tests that prove each CLAUDE.md control for the new tables: `content_roles`,
   `tenant_login_policy`, `jobs`, `sites`, `site_pages`, `downloads`, the consent columns on
   `users`, `usage_ledger.reasoning_tokens`, and the `askspore_retention` role. Sign the
   review as findings **section 8.1** with the commit hash, as in Phase 1a §10 "Isolation
   review".
3. Independent review: a second session (launched by the orchestrating session, as in
   Phase 1a §12) reads the release diff `main` since the Phase 1a close (6516048) for the
   non-negotiables and the two reviews' notes (findings §7), and signs or blocks. Its report
   goes into findings **section 8.2**.

### 2. Live checks: sign-in, SSO, mail

1. **Platform mail** (P1b-11): send one invitation to `daniel+cc@myceliumgastronomy.com`
   through the API (resend from the tenant admin page if the user exists). Owner confirms
   delivery, the SporeBot subject, the first-name greeting, SPF/DKIM/DMARC pass, and that the
   sender is the reply address. Record the `send_mail` job state and timings.
2. **Sign-in hardening** (P1b-08), each pass/fail: per-IP limit on `POST /auth/link`
   (owner triggers from outside), session refresh before expiry (shorten the validity in a
   test only if the owner agrees; otherwise verify the refresh call against Authentik's
   token endpoint and record it as desk-checked live), sign-out revokes the Authentik token
   (refresh after sign-out is refused), `no_binding` message text.
3. **Admin second factor** (decision 7): the first tenant admin sign-in with the admin group
   requires TOTP enrolment; a second sign-in asks for the code; a user without the group is
   not asked.
4. **SSO per connector** (P1b-07), on tenant `ssotest`, each in turn: operator configures
   the source in the console with the owner's IdP details (owner enters the secret);
   the console shows the redirect URI or ACS URL; owner registers it at the IdP; owner signs
   in from the IdP; JIT provisioning creates the user only for a verified domain; a user from
   an unverified domain is refused; `ask_spore_tenant` is the source's tenant; audit events
   `auth.login` with `method = sso:<kind>`; sign-out. Then remove the source and confirm
   Authentik no longer has it. Record per kind: pass/fail and the fix rows.
5. **Provisioner cleanup**: if the blueprint added `ask-spore-provisioner` beside the
   Phase 1a account, switch `AUTHENTIK_API_TOKEN` to the new account's token, restart the
   api, confirm a console action still works, then remove the old account.

### 3. Consent gate live (P1b-10) — after owner input 1

1. Put the owner's wording into `config/consent/v1.md` on `phase-1b/release`, push, merge,
   pull, restart the api. The startup warning about the placeholder must be gone.
2. Owner signs in as the `cc` test admin: the notice is shown, nothing works before
   acceptance (one conversation POST refused with 403), acceptance is audited, the routes
   open. The tenant admin's audit export carries the acceptance event and no body text
   (owner checks the CSV's columns, reports column names and row count only).
3. Do **not** bump the version on the live Instance; the re-prompt and the notice email
   are covered by the test suite.

### 4. Content pipeline drills (P1b-01 to P1b-05)

On a synthetic source only (a file from `packages/eval/fixtures/`, never a client file):

1. Propose, approve (self-approval audited), worker ingests; the register shows
   `ingested` with document IDs and chunk counts; the file is downloadable from a workspace
   whose tag it carries.
2. **Takedown drill** end to end: raise a takedown with a reference; the due date is 10
   working days; withdraw on licence grounds; the document is gone from every dataset
   (`ask-spore datasets` count), the tenant answer cache entries citing it are purged, a
   stored citation renders as withdrawn with a blanked excerpt (decision 5). Record timings.
3. **Crawl drill** on one small public site the owner names (or the Instance's own docs
   page): robots and TDM honoured, the pinned-address fetch works against a real HTTPS host
   (findings §7 note on SNI), pages registered, a re-crawl changes nothing, withdraw one
   page. Then withdraw the site.
4. Clean up: withdraw the synthetic source; confirm `datasets` counts are back to the
   Oct 20 ingestion figures (findings 1a §9).

### 5. Operator console and spend (P1b-12)

1. One tenant per page: open `cc`, save entitlements unchanged, confirm the audit event
   names `cc`; the workspace tag picker offers `cc-*` and `cc-shared` only.
2. Spend page: month-to-date figures match a `usage_ledger` sum the session reads directly
   (counts and cents only). Aggregates page shows no query text.

### 6. Retention (P1b-14)

1. `ask-spore purge --dry-run`: counts per tenant and table. Then `--run --wait`: the job
   succeeds; counts logged; no body in the worker log (grep the log for the dry-run's
   conversation count only).
2. On `ssotest` (not `cc`): set retention to 0 as its admin, ask one question, confirm no
   conversation row remains and the cache namespace is empty.
3. **Termination purge drill**: `ask-spore tenant purge --slug ssotest --confirm ssotest`
   as the schema owner. Certificate file written under `content_root/certificates/`
   (name and SHA-256 recorded, contents not printed); audit `tenant.purged`; the
   Authentik users of `ssotest` removed by hand and recorded.

### 7. Evals through the OIDC eval path (P1b-15 a, P1b-16)

1. One-time: `python -m eval keygen --out-dir /srv/ask-spore/eval-keys`;
   `ask-spore eval-identity create --email eval-service@myceliumgastronomy.com`.
2. Temporary api container `askspore-eval-api` on `127.0.0.1:8001` with a config copy that
   adds only `[auth.eval_service]` (README "Release step"); the live api never carries it.
   Flush nothing in Redis.
3. Eval set v1 on `deepseek-v4.1-flash`, `corpus_only/v5`, judge per owner input 7, against
   the temporary api; `eval compare` with the committed baseline. A regression beyond 3
   points is a stop to raise, not to fix silently. Then the guardrail eval, live.
4. `vector_similarity_weight` tuning (P1b-15 e): one run each at 0.2, 0.3 and 0.4 on eval
   set v1; report the metric table; the owner picks; the chosen value goes to
   `config/models.toml` on `phase-1b/release`.
5. Reasoning tokens: one Qwen call with reasoning on; the `chat.answer` line carries
   `reasoning_tokens` as an integer and the ledger row has it.
6. Remove the temporary container. Commit the chosen run with `accept-baseline --reason
   "P1b-16 release run"` only if the owner accepts it; redacted results only.

### 8. Close-out

- Findings **section 8**: release status, 8.1 isolation review signed, 8.2 independent
  review, live-check table (sections 2 to 7), F-rows, model and eval tables, the exact
  `main` commit the Instance runs, and what the owner still has to do.
- `design/compliance/paperwork-checklist.md`: update rows the release touched (TOTP configured,
  deletion wording to match the purge job).
- Backlog: every deferral from this release as a dated line.
- Spec status line: "Phase 1b closed" with the date, once the owner confirms.
- Final report to the orchestrating session (relayed by the owner): what passed, what did
  not, open owner items.

## Not in this release

External models for `cc` (P1a-15 gate), the sign-in-link test against the client's real
mail scanner (P1b-13 a, waits for the client's IT contact), branch protection (P1b-13 c,
owner skipped), `cc-shared` content (stays empty), Object Storage for the content store and
the two-host deployment (priority 4), client-supplied documents step 2 (P1b-19), anything in
Phase 2. Record ideas in `design/specs/backlog.md`.
