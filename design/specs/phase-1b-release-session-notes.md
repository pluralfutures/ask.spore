# Phase 1b release: session notes of Oct 22, 2026 (P1b-16)

Handover for the orchestrating session, written by the remote-control session on the
Instance at the end of the first release evening. Metadata only: no secret, address beyond
the test accounts the runbook names, query, answer or document text. The authoritative
record is `phase-1b-findings.md` §8; this file is the narrative, the open questions and the
resume plan. Times are UTC.

## State at the pause (Oct 22, 2026, about 23:45)

- **Instance runs `main` at bd1bc46** (`ASK_SPORE_DEPLOY_VERSION=bd1bc464ca60`): API, worker,
  migrate and web images built from it; Alembic head **0041**. `main` has since moved to
  12f903e (PR #52: independent review, backups note; documentation only, no rebuild needed).
- **Working tree `/root/ask.spore` is on `main` (12f903e).** All release changes are on
  **`phase-1b/release` (pushed, not merged)**, 13 commits ending 3edd9a9 (this file adds one).
  The owner's first "merged" was PR #52, not this branch.
- **Running** (at writing): postgres, redis, api, worker, caddy (production Caddyfile),
  the three Authentik services, RAGFlow with es, mysql, minio, redis and **tei**. The owner
  is about to stop the stack (`docker compose -f infra/compose.dev.yml --profile auth
  --profile public down`, no `-v`) and power the Instance off. No job was queued or running.
- **Test data left on purpose:** tenant `ssotest` with 3 JIT users (one per SSO connector)
  and no SSO source, no workspace; `cc` admin daniel+cc2 (TOTP enrolled, consent v1);
  Authentik users for those four. All removed in 6.3 and close-out.
- **Removed:** the Keycloak drill (container, volume `ask-spore-dev_keycloak_drill`,
  `/srv/ask-spore/drills/`), the throwaway test PostgreSQL containers, the synthetic source
  and all 19 crawled pages (withdrawn; datasets back to the Oct 20 counts).

## Owner decisions received this session

| Item | Decision |
| --- | --- |
| Q1 moved image tags (0.3) | Keep the existing pins for the release; record old and new digests; backlog: re-pin after reading each publisher's changelog, own PR, suite run. |
| Q2 default database passwords | Not during the release; backlog "rotate every default or example password … before the first customculinary.com user is invited, with a written rotation procedure"; list the defaults by name in §8. |
| F2 re-send | Option (a): re-queue the failed invitation job by hand as schema owner. |
| 4.3 crawl target | `https://www.myceliumgastronomy.com`, max 20 pages. |
| 5.1 `sample-*` tags offered to clients | Option (a): `tenant = "internal"` (F4); backlog "tags default to internal, sharing explicit" before the first client user. |
| SSO refusal as HTTP 500 in Authentik | Backlog, marked **before the first client user**. |
| 6.2 | Invite `daniel+ssotest@pluralfutures.com` as `ssotest` admin; owner enrols TOTP. |
| Orchestrator, 1.3 | Independent review signed, no blocker (`design/specs/phase-1b-independent-review.md` on `main`); its `jobs` ruling and four follow-ups are backlog lines. |
| Orchestrator, 2.1 | DMARC `p=none` on the organisation domain as a pre-launch backlog line; remove daniel+cc2 at close-out. |

## What was done, section by section

### 0. Bring-up

- **0.2** `.env` and `infra/authentik/.env` carry every key their compose files need (names
  only). `POSTGRES_PASSWORD` and `APP_DB_PASSWORD` are unset, so both database roles use the
  documented Compose dev defaults (Q2).
- **0.3** `image-digests.py --check` against Docker Hub: 14 pins match, **3 tags moved**
  (Authentik's `postgres:16.15-alpine`, `redis:7.4.11-alpine`, `caddy:2.11.7-alpine`; Hub
  rebuilt them Oct 21, 21:14 to 22:57). Kept (Q1). Digests in §8.
- **0.4** Authentik blueprint: dry run valid; applied by starting the three Authentik
  services only (a bare `--profile auth up -d` would start `migrate`, `api`, `worker` and
  RAGFlow on old images). `verify_blueprint.py` ok. Adopted the existing provisioner (one
  account, so step 2.5 had nothing to do); changed the provider (`refresh_token` grant,
  `offline_access`, refresh validity 30 days → 24 hours) and bound the admin MFA stage;
  created the source flows, MFA stages and group `ask-spore-tenant-admins`.
- **0.5** **F1**: the runbook built `api web-build worker` but not `migrate`, which has its
  own image; migrate ran the Phase 1a image and left the database at 0012. Built `migrate`,
  head 0041. `/healthz` 200 over TLS, `auth/mode` `oidc`, no consent-placeholder warning,
  public listeners 22/80/443 only. RAGFlow started by hand (not in the runbook's `up` line).
- **0.6** Content roles granted to the operator, audited.

### 1. Isolation tests and review

- **1.1** Full suite at bd1bc46 against a throwaway PostgreSQL 16.15 (same pinned digest,
  tmpfs; not the live cluster, whose roles the migrations would touch): **1345 passed**,
  1 deselected (`test_ragflow_integration`); ruff and `mypy --strict` clean. Run with `uv` on
  the Instance at the release commit (the API image has no tests or dev dependencies).
- **1.2** Signed in §8.1 with the tests per new table. Note raised for 1.3: `jobs` has no
  tenant RLS but carries `tenant_id`/`user_id` in mail payloads since 0030; no tenant-facing
  route reads it.
- **1.3** Independent review signed by the orchestrating session's reviewer, no blocker;
  ruling on `jobs`: acceptable now, RLS by payload `tenant_id` plus a cross-tenant test
  before any tenant-facing route reads it.

### 2. Sign-in, SSO, mail

- **2.1 Platform mail: pass after F2.** `SCALEWAY_TEM_API_KEY` was not in the root `.env`
  (the runbook said it was); the worker had only warned at startup, and the invitation for
  daniel+cc2 failed `mail_not_configured` before any provider call. The owner added the key;
  worker and api recreated; job `459fc857…` re-queued by hand, sent in 481 ms, `mail.sent`
  audited. Owner confirmed delivery, SporeBot subject, first-name greeting, SPF/DKIM/DMARC
  pass, From the reply address.
- **2.2** Per-IP link limit: 8 × 202 then 429 from the owner's machine (2 earlier requests
  in the window), no IP or email in the logs. Sign-out: `auth.signed_out` `revoked` and 0
  Authentik tokens left, for every user tested. `no_binding`: exact message, link not spent.
  Session refresh: desk-checked live (configuration only; no renewal fell due).
- **2.3** Admin TOTP: enrolment on first sign-in, code only on the second, non-admins never
  asked. Enrolment shows the key as text and an `otpauth://` link, no QR code (by design,
  findings B15); backlog for a QR code.
- **2.4 SSO**, tenant `ssotest` (verified domains `pluralfutures.com`,
  `myceliumtest001.onmicrosoft.com`; JIT on):
  - **Entra ID: pass.** First attempt refused cleanly (Microsoft `AADSTS7000215`: the secret's
    ID entered instead of its value). Then JIT user, tenant attribute, audit, sign-out.
  - **Google Workspace: pass.** pluralfutures.com user signed in (the second-factor prompt was
    Google's own 2-Step Verification). A myceliumgastronomy.com account (verified for `cc`)
    was refused, nothing created in any tenant.
  - **Generic OIDC: pass**, against a throwaway Keycloak 26.7.5 on
    `idp-test.askspore.myceliumgastronomy.com` (`infra/drills/keycloak/`; secrets generated
    outside the repo, read by the owner in their own terminal). Verified user in, outsider
    refused. Drill removed afterwards.
  - **SAML**: desk-checked only.
  - Notes (backlog): audit records `method=sso` without the kind; a refusal is an exception in
    the generated Authentik mapping, so Authentik logs HTTP 500 and `configuration_error`
    (owner: before the first client user); the console's SSO form keeps old values after
    removal.

### 3. Consent gate

- Wording released before the session; no placeholder warning. daniel+cc2's first sign-in:
  notice shown, the app's calls refused 403 `consent_required` until acceptance,
  `consent.accepted` v1 audited; the owner's console `POST /conversations` came after
  acceptance and got 422 (body), i.e. the gate opened. Audit export: columns
  `created_at,event,actor_user_id,metadata`, 25 data rows matching the database, includes the
  acceptance, no free text. Owner input 3 (download events in the export) was already done on
  Oct 22 (decision 18, eba1c77). Version not bumped.

### 4. Content pipeline drills

- **4.1** Synthetic DOCX under internal tag `sample-analysis`, proposed and self-approved
  (audited). **F3**: `ragflow-tei` (embedding) was not running, because neither the runbook nor
  RAGFlow's `depends_on` starts it; the first ingestion failed `parse_failed`. No chat question
  was asked in that window. TEI started, source retried and ingested (1 chunk). Fix:
  `ragflow` depends on `ragflow-tei`, runbook 0.5 starts `ragflow`. The owner downloaded the
  file from the internal `research` workspace.
- **4.2 Takedown drill: pass.** Question answered with a citation, repeated from cache; takedown
  on licence grounds due **2026-11-05** (10 working days); withdrawal 1.6 s end to end; datasets
  back to baseline, both citations withdrawn with blank excerpts, cache emptied; the owner's next
  two questions were withheld (`answer_withheld`).
- **4.3 Crawl drill: pass.** Owner's site, robots `*` group applies to our crawler, no TDM
  reservation: 19 pages ingested (35 chunks), 2 blocked (`noai_or_noindex`,
  `duplicate_content`); pinned-address HTTPS fetch works (SNI question settled). Re-crawl: no
  change at all. One page withdrawn (page `blocked`/`withdrawn`); "withdraw the site" has no
  site-level action (decision 8), so the other 18 pages were withdrawn one by one; site row
  stays `approved`. Backlog for a site-level withdrawal.
- **4.4** Every RAGFlow dataset count equals the Oct 20 figures.

### 5. Operator console and spend

- **5.1** Unchanged entitlements save landed on `cc` only (`updated_at`); no audit event because
  nothing changed (by design; the runbook expected one). No visible confirmation in the console
  (backlog). Tag picker offered the three `sample-*` tags as shared to `cc`: **F4**, owner chose
  `tenant = "internal"`; tests updated and added, **1347 passed**. Committed on the release
  branch; **not live until merged and pulled** (see "Caveats").
- **5.2 pass.** `cc` Spend and the aggregates page equal `usage_ledger` to the token and cent;
  no question text on the aggregates page.

### 6. Retention

- **6.1 pass.** Dry run: 0 due (no history older than 30 days yet; per-table lines appear only
  for non-zero counts). Run: `purge_retention` succeeded in 57 ms; 2 worker log lines, no body
  fields.
- **6.2, 6.3: not started.**

### 7, 8: not started.

## F-rows (findings §8)

| # | What | Status |
| --- | --- | --- |
| F1 | Runbook 0.5 omitted the `migrate` image | Fixed (runbook) |
| F2 | Mail API key missing from `.env` | Fixed (owner added it; job re-queued) |
| F3 | `ragflow-tei` not started; RAGFlow does not depend on it | Fixed in compose and runbook; TEI started by hand on the live stack |
| F4 | `sample-*` tags shared with client tenants | Fixed in `config/tags.toml` and tests; live after merge |

## Backlog lines added (all dated Oct 22, 2026)

Re-pin the three moved images; rotate default passwords before the first client user (pre-launch);
`jobs` RLS before any tenant-facing read; `FetchError` messages never logged; Compose
non-loopback port test; lower `downloads_days` cap; DMARC `p=none` (pre-launch); SSO kind in the
login audit; SSO refusal not as an Authentik 500 (**before the first client user**); clear the SSO
form after removal; QR code for TOTP enrolment (pre-launch); site-level withdrawal; link from the
operator console to the chat app; tags default to internal with explicit sharing (**before the
first client user**); visible save confirmation in the console.

## Caveats for the reviewer

- **Working tree and live config.** The api and worker read `config/` from the working tree, and
  the operator API reloads `tags.toml` per request. During this session the tree was on
  `phase-1b/release` while drills ran; the only live-relevant difference was F4's `tags.toml`
  (live for a few minutes, reverted when the tree went back to `main`). From now on, branch work
  should use a separate `git worktree` so the live tree stays on `main`.
- **Untracked eval results.** `packages/eval/results/` on the Instance holds 8 untracked,
  unredacted Oct 21 run folders. They make the eval package's `test_the_repository_gate_passes`
  fail locally (CI never sees them). Never commit them; the owner may want them deleted or moved
  out of the repository tree (owner decision; not touched).
- **The SSO and consent checks used the owner's real test identities** (Entra trial user, Google
  Workspace accounts); none of their addresses is in this file or the findings beyond the domains.
- **Not replayed live:** a refresh-token call after sign-out (evidence: Authentik holds no token
  for the user); the conversation POST before acceptance (evidence: the gate's refusals and the
  test suite).

## Resume plan (next session)

1. **Owner:** merge `phase-1b/release` (F3, F4, records, drill files, this file). Power on.
2. **Session:** `git -C /root/ask.spore pull` on `main`; confirm the commit. Bring-up, with names
   only from `.env`:
   ```
   export ASK_SPORE_DEPLOY_VERSION=bd1bc464ca60   # images unchanged; app code identical to bd1bc46
   docker compose -f infra/compose.dev.yml --profile auth up -d authentik-postgresql authentik-server authentik-worker
   docker compose -f infra/compose.dev.yml up -d migrate          # head stays 0041
   docker compose -f infra/compose.dev.yml --profile public up -d ragflow api worker caddy
   ```
   Check: `/healthz` 200, `auth/mode` `oidc`, `ragflow-tei` running (RAGFlow now pulls it in),
   worker log without `worker.mail_not_configured`, dataset counts equal the Oct 20 figures,
   `cc`'s tag picker offers only its four tags (F4 live).
   (If `main` changed app code since bd1bc46, rebuild `migrate api web-build worker` and set the
   deploy version to the new commit; at 12f903e plus this branch it has not.)
3. **6.2 (owner at the keyboard, one step per message):**
   a. Console, tenant `ssotest`: invite tenant admin `daniel+ssotest@pluralfutures.com`; add
      workspace `drill` / "Drill" with no tags. Session confirms the `send_mail` job and the
      workspace.
   b. Owner signs in from the invitation (TOTP enrolment, accept the notice).
   c. Tenant admin page: retention 0 (no history). Ask one question in `drill`. Session confirms
      no conversation row remains for `ssotest` and its cache namespace is empty (I-4 also clears
      it on the switch).
4. **6.3 termination purge drill:** `ask-spore tenant purge --slug ssotest --confirm ssotest` as
   schema owner (via the `migrate` service, as for content roles). Record the certificate file
   name and SHA-256 (not its contents), audit `tenant.purged`; then remove `ssotest`'s Authentik
   users by hand (the 3 JIT users and the new admin) and record their count.
5. **7 evals:** keygen to `/srv/ask-spore/eval-keys` (root only), `eval-identity create`,
   temporary `askspore-eval-api` on 127.0.0.1:8001 with `[auth.eval_service]` only in a config
   copy; eval set v1 on `deepseek-v4.1-flash`, `corpus_only/v5`, judge `qwen3.8-27b`;
   `eval compare` with `BASELINE` (regression > 3 points is a stop); guardrail eval; weight runs
   at 0.2/0.3/0.4 (**owner picks**); one Qwen reasoning call (`reasoning_tokens` in the log line
   and ledger); remove the container; `accept-baseline` only if **the owner accepts**.
6. **8 close-out:** remove daniel+cc2 (database user and Authentik user), finish §8 (status,
   model and eval tables, exact commit), paperwork checklist rows (TOTP configured; deletion
   wording vs the purge job), spec status line once the owner confirms, final report.

## Owner items still open

- Merge `phase-1b/release`.
- 6.2 sitting (invite, TOTP, retention 0, one question).
- 7: choose `vector_similarity_weight`; accept or not the release eval run as baseline.
- Decide what to do with the 8 untracked Oct 21 eval result folders on the Instance.
- Restore test of the nightly backup (recorded as open on `main`, dae6e2a).
