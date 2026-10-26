# Phase 1c release runbook (P1c-16)

Brief for the session that releases Phase 1c on the Instance. Written Oct 23, 2026 by the
orchestrating session after PR #59 (`phase-1c/integration`) merged into `main`. Read
`CLAUDE.md`, `phase-1c-build-spec.md` (both decision tables), `phase-1c-findings.md`
(sections 1 to 4; section 3.1.3 holds the live-eval instructions), the Phase 1b release
record (`phase-1b-findings.md` §8) and `infra/README.md` (deploy script, credentials
rotation, mail domain policy, backups) first. This runbook adds nothing to the spec; it orders
the release work and fixes the values.

## Ground rules

Same as the Phase 1a and 1b runbooks:

- Run on the Instance from `/root/ask.spore` on `main`. Branch work happens in a separate
  `git worktree` under `/root` (the live tree stays on `main`: Phase 1b caveat); changes go
  on branch `phase-1c/release`, pushed for the owner to merge, then pulled. Never push to
  `main`; never open a PR.
- Metadata-only output: never a value from any `.env`, a key, a token, a link, a client
  secret, a document's contents, a query or an answer. Key names, counts, status codes,
  file names, timings.
- No wildcard or recursive deletes outside the documented restore-test teardown; do not
  remove volumes of the live project, `/srv/ingest-out/`, `/srv/ask-spore/eval-runs/` or
  `/srv/ask-spore/eval-keys/`.
- Owner decisions arrive in this brief or in a later message quoting the owner. Anything
  else that needs a decision: stop that item, report, continue with the rest.
- CLAUDE.md non-negotiables are release blockers. A fix goes to `phase-1c/release`, merged by
  the owner, pulled, redeployed by the script, and the affected check re-run. Every fix is an
  F-row in findings section 5.

## Fixed values

| Item | Value |
| --- | --- |
| Public host | `askspore.myceliumgastronomy.com` |
| Release commit | `main` after PR #59 (the session records the exact hash) |
| Deploy | `infra/scripts/deploy.sh --public-url https://askspore.myceliumgastronomy.com` (P1c-10); never by hand |
| Credentials | Rotated by the owner before the deploy (decision 9); the deploy script refuses otherwise |
| Image pins | Re-pinned at integration (findings 1c §4 I-6); `--check` on the Instance must pass for every reference including the Keycloak drill image |
| Eval baseline | `packages/eval/results/BASELINE` = the Phase 1b release run at weight 0.4 (Oct 23) |
| Eval service identity | `eval-service@myceliumgastronomy.com`; keys under `/srv/ask-spore/eval-keys/` (from Phase 1b) |
| Eval full outputs | `/srv/ask-spore/eval-runs/` (P1c-12 default); only redacted results under `packages/eval/results/` |
| Active prompt | `corpus_only/v5`; `v6` is the candidate (P1c-13), switched only on the acceptance rule in findings 1c §3.1.3 |
| SSO test tenant | `ssotest` again (slug free since the Phase 1b termination drill), verified domains `pluralfutures.com` and `myceliumtest001.onmicrosoft.com`; Entra trial tenant and Google Workspace as in Phase 1b; Keycloak drill (`infra/drills/keycloak/`) on `idp-test.askspore.myceliumgastronomy.com` for generic OIDC |
| Test users to remove at close-out | `daniel+cc2@myceliumgastronomy.com` was removed at the Phase 1b close-out; anything this release invites is removed through the new P1c-07 action (which is itself a check) |

## Owner inputs needed before the session starts

1. **Rotation window.** About twenty minutes at the owner's terminal for section 0: database
   roles, Authentik bootstrap token and admin password, RAGFlow only if the host check names
   it (procedure: `infra/README.md`, "Credentials rotation"). The deploy cannot start before.
2. **Keyboard block** (one sitting, about forty minutes): one refused SSO sign-in per kind,
   one successful one for Entra, the TOTP enrolment QR code, resend and remove-user actions,
   the two checks Phase 1b did not replay live.
3. **DMARC**: whether the aggregate reports since Oct 22 are clean (the session reads only the
   counts the owner relays). The DNS change itself is the owner's, outside the session.
4. **Backup**: location and format of the nightly volume backup (`/srv/backups` and archive
   names, no content) for the restore test.
5. **Eval decisions at 5.4**: v6 acceptance and the baseline, on the metric table.

## Order of work

### 0. Credentials rotation (owner, before anything else)

The owner runs `infra/README.md` "Credentials rotation" steps 1 and 2 in their own terminal,
then `python3 infra/scripts/check-credentials.py` must exit 0 (key names only). The session
confirms the exit code and that the api and worker restarted on the new values (healthz 200,
startup lines), then records it as 0.1. Nothing from the rotation is pasted to the session.

### 1. Deploy by script (P1c-10)

1. Owner powers the Instance on (if off); the session opens as a remote-control session.
2. `git -C /root/ask.spore pull` on `main`, record the commit; `--dry-run` first, then the
   full `deploy.sh --public-url ...`. Expected: digest check passes for every reference
   (quay.io reachable from the Instance), credentials step passes, images built including
   `migrate` and `web-build`, Alembic head **0060**, RAGFlow with `ragflow-tei`, api and
   worker recreated, `/healthz` 200 over TLS, `auth/mode` `oidc`, no
   `worker.mail_not_configured`, dataset counts equal to before, summary printed.
3. Any failure is an F-row; fix on `phase-1c/release`, merge, redeploy.

### 2. Isolation tests and the independent review

1. Full `pytest` with the database tests against a scratch database on the Instance's
   Postgres (never the live database). Expected 1511 passed at the integration head.
2. Findings **section 5.1**: the control-to-test table extended for the Phase 1c changes
   (jobs RLS, user-removal role, message flags, tags default, SSO refusal path, credentials
   check), signed with the commit hash.
3. Independent review (launched by the orchestrating session) of `main` since the Phase 1b
   close (1a714fe); its report goes to **section 5.2**, verdict line plus a reference to the
   file it is filed in, as in Phase 1b.

### 3. Live checks (owner at the keyboard, one step per message)

1. **Pre-existing SSO sources** (decision 11): if `tenant_login_policy` holds any SSO row,
   re-save it from the console before the refusal checks (none expected).
2. **SSO refusals per kind** (P1c-02): create `ssotest` again with its two verified domains
   and JIT on; configure Entra, then Google, then the Keycloak drill (owner enters secrets in
   the console; the Keycloak drill is brought up and torn down as in Phase 1b). For each
   kind: one sign-in from an unverified-domain user ends on our landing page with the coarse
   reason, no Authentik error page, no `configuration_error` event, `auth.login_failed`
   with `method = sso:<kind>`; one successful Entra sign-in shows `auth.login` with
   `sso:entra`. Remove each source afterwards and confirm the console form is cleared.
3. **The two checks Phase 1b did not replay**: (a) sign out, then a refresh-token call for
   that session is refused (401) and Authentik holds no token; (b) a fresh user's first
   conversation POST before consent is refused (403 `consent_required`), then accepted after.
4. **Admin second factor**: the TOTP enrolment page shows the QR code and the text key; the
   owner enrols the `ssotest` admin from the QR code alone.
5. **Invitations and removal** (P1c-07): invite a second `ssotest` user, resend once (one
   `send_mail` job, audited), a second resend while queued returns the same job; the first
   invite's `email_taken` shows as a message; remove that user through the tenant admin page
   (audited, Authentik account deactivated, no row outside `audit_events`); the last admin
   cannot be removed; the operator cannot remove an internal user with a content role.
6. **Console feedback** (P1c-08): every save shows "Saved" or the error; the console-to-chat
   link appears for the operator and the chat-to-console link only for operators; the
   terminated tenants page lists the Phase 1b `ssotest` purge with its certificate number
   (and not `cc`).
7. **Chat history** (P1c-09), as the `ssotest` admin on a workspace with the sample tags
   (internal `research` workspace is simpler: the operator as an internal user): stop an
   answer mid-stream, reload, the partial answer and its note are there; a cut-off answer
   shows its note after reload (if one occurs; otherwise record as covered by tests).
8. **Tags** (P1c-01): `ssotest`'s workspace picker offers no `sample-*` tag; the internal
   `research` workspace still has them.

### 4. Content drills (P1c-14)

On synthetic sources only: register a second version of the Phase 1b drill file under the
same canonical link and title (auto-replacement, "Replaces" shown, old excerpts kept);
then under the same link with another title (flagged as possible replacement); withdraw a
source for a non-licence reason and confirm its citation excerpts are blanked and labelled
withdrawn; crawl the owner's site again (max 20 pages), withdraw one page, restore it, then
withdraw the whole site and confirm no page remains in any dataset and the schedule is gone.
Dataset counts return to the Oct 20 figures.

### 5. Evals (P1c-13), per findings 1c §3.1.3

1. Temporary api `askspore-eval-api` on `127.0.0.1:8001` with the config copy carrying only
   `[auth.eval_service]`, deploy version `<release sha>-r2` so every answer is fresh without
   flushing the live cache. Full outputs to `/srv/ask-spore/eval-runs/`.
2. **Second run at weight 0.4, v5**: confirms the Oct 23 tuning; compare with `BASELINE`.
3. **v6 on eval set v1** (second config copy differing only by `[prompts] corpus_only = "v6"`;
   remove and recreate the temporary container); then **v5 and v6 on the live guardrail
   eval**.
4. **Acceptance rule** (findings 1c §3.1.3; decision 12): no metric drop beyond 3 points
   against the baseline or the second run; hc-v1-039 answered with a citation; hc-v1-055 and
   hc-v1-058 not answered with one; guardrails no block below v5's result (the accepted
   `03-drop-citations` aside). If it holds, switch `[prompts] corpus_only` to `v6` on
   `phase-1c/release` and accept the v6 run as the new baseline (redacted) in the same PR;
   if only some items move without regression, keep v5 active, record the known limits
   (decision 12) and leave v6 as the candidate; if anything regresses, v6 is not adopted.
   The owner decides on the metric table.
5. Remove the temporary container; confirm `packages/eval/results/` holds redacted results
   only and the gate passes on the Instance tree.

### 6. Backups (P1c-12), image pins (P1c-06), mail domain (P1c-05)

1. **Restore test** per `infra/README.md`: restore the latest nightly backup into the scratch
   project `askspore-restore`, compare row and dataset counts with the live figures taken at
   the same time, record the deltas with the times, tear the scratch project down with its
   volumes (the only `down -v` of this release, scoped to that project). Set up the nightly
   content-store copy next to the volume backup and confirm the first copy exists (size and
   date only).
2. `python3 infra/scripts/image-digests.py --check` without the mirror: every reference
   pinned, including `quay.io/keycloak`.
3. DMARC: record the owner's report summary (counts) and whether `p=quarantine` is set; if
   not yet, it stays a pre-launch owner item with the date of the clean week.

### 7. Close-out

- Findings **section 5**: release status, 5.1 isolation review signed, 5.2 independent
  review, the live-check table, F-rows, the eval tables and decisions, the restore-test
  record, the exact `main` commit the Instance runs, and the owner's remaining items.
- Remove `ssotest` with the termination purge again (the certificate is the second one;
  record its number), remove its Authentik users and the Keycloak drill.
- `design/compliance/paperwork-checklist.md`: rows touched (credentials rotated, DMARC,
  restore test, deletion wording).
- Backlog: every deferral as a dated line; strike what this release closed.
- Spec status line: "Phase 1c closed" with the date, once the owner confirms.
- Final report to the orchestrating session, relayed by the owner.

## Not in this release

The first `customculinary.com` invitation (owner action after the paperwork gate; not an
exit criterion by decision), external models for `cc`, Object Storage and the two-host
deployment, client-supplied documents step 2, the relevance-check item, the UI refresh
(decision 5), anything in Phase 2.
