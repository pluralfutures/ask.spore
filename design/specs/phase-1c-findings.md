# Phase 1c findings

Section 1 is Group A's, section 3 Group D's; each group writes its own section on its own
branch, and the orchestrating session merges them.

## 2. Where the Groups B and C build differ from the spec

Branch `phase-1c/group-bc`, from main plus the approved spec (eb8caf3). Built Oct 23, 2026.
One commit per item:

| Item | Commit |
| --- | --- |
| P1c-09 chat history completeness | ca0efb4 |
| P1c-07 invitations and user removal | 3180def |
| P1c-08 console feedback | 4f26b58 |
| P1c-11 CI reliability | 3bddc21 |
| P1c-10 deploy script | 5d1bd21 |
| P1c-12 backups and eval outputs | f8e7775 |

**Migrations: 0050** (`messages.truncated`, `messages.partial`; down_revision **0041**) and
**0051** (role `askspore_user_removal`, `workspace_prompts.author_user_id` nullable;
down_revision 0050). P1c-09 was built first because it owns 0050. Group A's 0042 runs in
parallel: at integration, re-parent 0050 onto Group A's head (one `down_revision` line).

### P1c-07 Invitations and user removal

| Spec says | Built |
| --- | --- |
| "Resend invitation" in the operator console and the tenant admin pages for a user still `invited`, re-queuing one `send_mail` job, audited | `POST /api/v1/admin/users/{id}/invitation` and `POST /api/v1/operator/tenants/{tenant}/users/{id}/invitation`: 422 `not_invited` unless the user is `invited`, 404 for another tenant's user; one job through `enqueue_invitation`, whose unique index returns the job still queued instead of adding a second (pressing twice queues one). Audited `tenant_admin.invitation_resent` / `operator.invitation_resent` with the `job_id`. Buttons in both user tables (shared `UserActions` component). |
| The tenant admin invite's 409 `email_taken` shown as a message | The tenant admin page already mapped it; the operator console showed "Refused (409)." The console's `errorText` now words `email_taken`, `domain_taken`, `slug_taken` and the removal codes, and shows `Refused (<status>: <code>)` for any other. |
| An audited "remove user" (tenant admin for their tenant, operator for any) deleting the user's account data and history as termination does for a tenant, keeping audit events and the ledger | `DELETE /api/v1/admin/users/{id}` and `DELETE /api/v1/operator/tenants/{tenant}/users/{id}`, both through `app.tenancy.user_removal.remove_user` in the caller's transaction. The application role cannot delete users, so the module takes a **new NOLOGIN role `askspore_user_removal`** for its statements (revision 0051; granted to `askspore_app` with `INHERIT FALSE, SET TRUE`, like the retention role), with `app.tenant_id` set to the user's tenant: the tenant tables' RLS bounds every deletion. It deletes the user's conversations with their messages, citations and feedback, the user's feedback elsewhere, downloads, revoked sessions, sign-in links, MFA challenges, the jobs whose payload names them and the `users` row, in termination's `PURGED_TABLES` order; it clears the user as author of prompt versions (`author_user_id` NULL: the versions are the workspace's) and as `jobs.created_by`. Audit events (they keep the user's ID as actor) and the usage ledger stay. Audited `tenant_admin.user_removed` / `operator.user_removed` with role, status before and the row count. |
| Reuse the termination module's table knowledge | Deletion order comes from `termination.PURGED_TABLES`; kept tables are checked against `KEPT_TABLES` in a test. Like termination's unknown-table guard, removal refuses (`unknown_user_table`) while any column naming a user (`user_id`, `*_user_id`, `created_by`, `proposed_by`, `approved_by`; read from `pg_catalog`) is not in its map. |
| Refuse the last tenant admin, the caller themselves, and any internal-tenant user with an operator or content role | 422 `last_admin` (no other tenant admin that is not deactivated), `cannot_remove_self`, `platform_role`. **Added:** `register_author`, a user named as proposer or approver in `sources` or `sites` (the register keeps its provenance; NOT NULL columns). |
| (not in the spec) | The user's Authentik account is **deactivated** (`is_active` false, new `SignInLinkProvider.disable_user`); the provisioner's blueprint role may change users but not delete them, so deleting the account stays a manual step, as for a terminated tenant (question 1). A provider failure rolls the removal back (502 `provider_not_updated`). Re-inviting the address works and re-activates the account. |
| Tests: resend queues exactly one job; removal leaves no row with the user's ID outside `audit_events` (every table with a user column from `information_schema`); a tenant admin cannot remove another tenant's user (zero rows, 404) | `tests/test_user_removal.py` (13): one job per resend and none for an active user or another tenant's; removal after arranging a row in every table that names a user, then every `information_schema` user column counted: only `audit_events.actor_user_id` remains; another tenant's user: 404, zero rows changed, no audit event; self, last admin (a deactivated second admin does not count), platform role, register author refused; the operator path; a provider failure leaves every row; plain users get 403; the app role alone cannot delete users and the removal role cannot read message text; the removal map equals the schema. `test_authentik_adapter`: deactivation is a PATCH, never a DELETE. Web: `admin.spec.ts` (resend, cancel then confirm removal, `email_taken`), `operator.test.ts`, `TenantAdmin.test.tsx`. |

### P1c-08 Console feedback

| Spec says | Built |
| --- | --- |
| A QR code on the TOTP enrolment page (render the otpauth URI as SVG client-side; no new runtime dependency unless a tiny hash-pinned one is unavoidable) | **No new dependency.** `apps/web/src/lib/qr.ts` is a QR encoder written here (byte mode, error correction M, versions 1 to 40, the standard's eight masks and penalty rules), drawn as one SVG path by `components/QrCode.tsx` above the key text. While building it, its matrices were compared with an independent encoder (python-qrcode 8, in a scratch environment, not a project dependency) for versions 1 to 29 and every mask: identical. The unit test carries two reference matrices from it. (segno 1.6.6 disagreed with both on the pad codewords, so it was not used as the reference.) |
| "Saved" or the error after every operator console save | `components/SaveStatus.tsx` on every console save: entitlements, login policy, SSO source save and removal, workspace creation, workspace tags, tenant creation, the download switch; plus the resend and removal status lines. |
| A link between the operator console and the chat app, and back, shown only to users who are also internal-tenant users | The console links to the chat app (every operator is an internal-tenant user). The chat app's conversation list links to the console when `GET /me` says `operator: true` (new field): an OIDC identity, not the eval service identity, of the internal tenant, listed in `operators`, the same test as `require_operator` (now shared as `listed_operator`). The flag opens nothing; the console's API still decides on every call. |
| Terminated tenants listed as `suspended` with purge date and certificate number from the `tenant.purged` audit event (Phase 1b F5) | `GET /api/v1/operator/terminated-tenants`: tenants without entitlements or a login policy, with `purged_at` and `certificate` from their `tenant.purged` event. That event is recorded under the internal tenant and names the purged tenant only by `before.slug`, so the match is by slug (slugs are unique and the row stays). Shown on the console page as "slug · suspended · purged <date> · certificate <number>". |
| Tests per behaviour, web and API | API `tests/test_console_feedback.py`: `operator` true only for an operator (internal non-operator, client admin false; the client admin still gets 403 from the console); a purged tenant listed with its certificate number and date, the others not; non-operators refused. `test_auth` exact `/me` body updated. Web: `qr.test.ts` (reference matrices, version choice, lowest-penalty mask, finder patterns, quiet zone), `FinishSignIn.test.tsx` (the URI as an image and as text; no image at the code step), `SaveStatus.test.tsx`, `e2e/operator.spec.ts` (links both ways, the terminated tenant, "Saved." after a login-policy save, the worded refusal after a refused tag save). |

### P1c-09 Chat history completeness

| Spec says | Built |
| --- | --- |
| Migration 0050: `messages.truncated` so the cut-off note survives reload and shows in history | 0050 adds `truncated` **and `partial`** (both boolean, default false, assistant messages only by a check constraint). `MessageOut` carries both; the web app shows "This answer was cut off at the length limit." / "This answer was stopped before it finished." from the stored flags (the per-visit `cutOff` set is gone). |
| A "stop generation" button that aborts the stream client-side and lets the server store the partial answer flagged `partial` | "Stop" replaces "Ask" while an answer streams and aborts the request. On the server the orchestrator wraps the stream (`_keeping`): once the model's stream has opened, a stream that closes before the turn settled stores the question and an assistant message with `partial = true`, holding **what the user had been shown** and the citations in it, from a shielded task (so the store survives the cancellation, as P1b-14's `_forgetting` does). After a stop the web app reloads the conversation until the stored turn is there. |
| When the model fails or the client disconnects mid-stream, keep the question and the flagged partial answer, except for no-history tenants, which must still leave no row | Model failure mid-stream (`LLMError` after the stream opened): partial turn stored, then the `error` event; one `chat.query` audit event with `status: partial` and the error code. Client gone: the same with `error_code: stopped`. **Corpus-only text held back before its first citation is never stored**: the partial answer is then empty and `unsupported` (the withheld rule, G6). A failure **before** the stream opens (entitlement refusal, retrieval, a model that does not open) still stores nothing (question 3). A partial answer is never cached. No-history tenants: untouched path, the conversation goes when the stream closes. |
| Tests: reloaded conversation shows the note; a stopped answer is stored partial; a disconnect stores partial; a no-history conversation leaves no row in both cases | `tests/test_partial_answers.py` (8): cut-off flag after reload (and none on a complete answer); stop (`aclose` after the first token) stores the shown text with its citation, audit `partial`/`stopped`, log line without text; a real disconnect (the consuming task cancelled while the model stream stalls) stores partial; held uncited text is not stored; mid-stream model failure stores partial, one audit event, nothing cached; a failure before the stream stores nothing; no-history: no row after a stop and after a mid-stream failure. Web: `answerNotes.test.ts`, `e2e/history.spec.ts` (notes after reload; Stop, then the kept partial answer). |

### P1c-10 Deploy script

| Spec says | Built |
| --- | --- |
| `infra/scripts/deploy.sh`: pull main or a named commit | Refuses a dirty tree; `git fetch`; `main` fast-forwarded to `origin/main`, or `--commit <sha>` checked out detached (`config/` follows it; question 6). |
| Image-digest check, fail closed, `--hub-mirror` passthrough | `image-digests.py --check` with `--hub-mirror` passed through; a moved tag or an unreachable registry stops the deploy. `image-digests.py` now reports a registry that does not answer in one line (exit 2) instead of a traceback. |
| Build every image including `migrate` and `web-build` | `build migrate api worker web-build` (F1). |
| Run migrations; start the Authentik services, RAGFlow with its embedding service, api, worker, Caddy | The three Authentik services alone (as the release did), `run --rm migrate`, the Alembic head read with `alembic current`, then `--profile public up -d ragflow api worker caddy` (RAGFlow pulls in `ragflow-tei`, F3). |
| Set `ASK_SPORE_DEPLOY_VERSION` from the commit | The commit's first 12 hex characters, exported for every Compose call. |
| Check /healthz, auth/mode, the worker's startup lines (no `worker.mail_not_configured`), the dataset counts; metadata-only summary | `/healthz` on loopback and, with `--public-url`, over TLS; `auth/mode` equals `--expect-auth-mode` (default `oidc`); `ragflow-tei` and `ragflow` running; `worker.started` seen and zero `worker.mail_not_configured` lines since the start (F2); RAGFlow's counts per dataset equal those taken before the deploy, through a **new `ask-spore datasets counts`** (tag, document and chunk counts as log lines). Summary: commit, deploy version, head, each check, counts per tag. `config --quiet` only; no environment is printed. A job ingesting during the deploy would change the counts and fail the last check (the services stay up). |
| Per-tenant answer-cache clear on deploy covered by the deploy version in the cache key: verify and say so | **Verified.** `Orchestrator._cache_key` includes `deploy={settings.deploy_version}`, read from `ASK_SPORE_DEPLOY_VERSION`, which the script sets from the commit for the api and the worker; `test_workspace_orchestration::test_cache_misses_after_a_deploy` shows a new version misses and the same version hits. No clear on deploy is needed; old keys expire with `cache_ttl_seconds`. |
| A `--dry-run` for CI (`compose config` and the digest check), in the CI Compose job | `--dry-run` runs `compose config --quiet` with the `auth` and `public` profiles and the digest check, nothing else; CI's Compose job runs it. **Until Group A's P1c-06 re-pins the three moved Docker Hub tags, this step fails on any branch** (it fails closed on moved pins, which is what it is for). From this container the check could not reach a registry at all (Docker Hub 429 on the shared address; the mirror is blocked by the session proxy), so the live digest check was not run here. |
| Tests: the dry run in CI; the RAGFlow to embedding-service dependency asserted | `apps/api/tests/test_deploy.py`: `ragflow` depends on `ragflow-tei`; the script's steps; the dry run with stand-ins for `docker` and `python3` (exactly `compose config --quiet` and `image-digests.py --check --hub-mirror …`, nothing built); a moved digest fails it closed; a malformed `--commit` is refused before any command. `test_datasets_sync`: counts per mapped tag, a dataset missing in RAGFlow reported as missing. shellcheck: no findings. |

### P1c-11 CI reliability

| Spec says | Built |
| --- | --- |
| Find the race in `admin › an admin saves the instructions as a new version` (`toHaveValue` after save) and fix the wait properly, not with retries | The race itself (the second fill landing before the first save finished, whose success then cleared the draft) was found and fixed in **P1b-13 f** (findings 1b D12: the editor keeps the draft until the reloaded history holds the save, the fake API answers a save after 300 ms). What remained weak: the test's waits, "Version history (n)" visible and the button disabled, **both also hold while the save's `onSuccess` is still running**, so the test could continue before the save had finished. The editor now shows "Saved as version N." once the history is reloaded and the draft settled, and the test waits for that status before checking the field. No retries. |
| Run it ten times in a row | 10 of 10 with `--repeat-each=10 --workers=1`; 40 of 40 with `--repeat-each=40 --workers=4`. |
| Record "branch protection: declined by the owner, Oct 23, 2026" and strike the backlog line | **Branch protection: declined by the owner, Oct 23, 2026** (Phase 1c decision 2, third ask). The backlog line is struck as an owner decision, not carried further. |

### P1c-12 Backups and eval outputs

| Spec says | Built |
| --- | --- |
| The restore-test procedure (scratch Compose project, counts compared) in `infra/README.md` for the release session | `infra/README.md` "Restore test": live counts first (every public table's exact row count through one `\gexec` query; RAGFlow per dataset through `ask-spore datasets counts`); the backup restored into `askspore-restore_*` volumes; `postgres` and `ragflow` started under `-p askspore-restore` on other loopback ports, no migration; the same counts from the scratch copy and `diff`; content file counts; recorded as counts only; `down -v` afterwards. Not run here (the Instance's backup is owner-held); P1c-16 runs it. |
| A nightly copy of the content store described in the same place | A root cron line copying the `content` volume read-only to a dated archive each night with 14 kept, beside the volume backup; the helper image to be digest-pinned before use; same destination and retention as the volume backup (question 7). |
| The harness writes full outputs under a configurable directory defaulting to `/srv/ask-spore/eval-runs/`, only redacted results under `packages/eval/results/`, so the gate passes with full outputs present | `eval/outputs.py`: `--runs-dir`, else `EVAL_RUNS_DIR`, else `/srv/ask-spore/eval-runs/` (created 0700). `run` writes the full folder there and the `gate.redact` copy under `results/`; a runs directory inside `results/` is refused (exit 2 before anything runs). Guardrail runs go to the runs directory only (`guardrails --results-dir` became `--runs-dir`; `guardrails.yml` updated). `eval.yml` passes `--runs-dir "$RUNNER_TEMP/eval-runs"` and still uploads the full folder as its artifact, as before (question 8). |
| Tests: the output paths; the gate on a tree with a full-output folder outside `results/` | `packages/eval/tests/test_outputs.py` (5): flag, environment and default; full outputs outside and the redacted copy under `results/` (no answer text in its JSON or summary, metrics and counts equal, folder 0700); refused inside `results/`, from the module and the CLI; the repository's `results/` copied into a tree with a new run's full folder outside it: the gate passes and checks the new run; the same full folder put under `results/` fails it. |

### Notes for the integration

- **0050 re-parent** onto Group A's head; 0051 stays on 0050.
- **`jobs` row-level security (Group A, P1c-04).** 0051 already creates policy `user_removal`
  on `jobs` for `askspore_user_removal` (payload `tenant_id` equals `app.tenant_id`), inert
  while `jobs` has no RLS. Once Group A enables it, `test_user_removal` proves removal still
  reaches the user's mail jobs; if Group A forces RLS with a different policy shape, adjust
  that one policy.
- **P1c-06 re-pins** make the new CI dry-run step green (above).
- **`backlog.md`**: this branch strikes eleven lines (P0-14, P0-16, the truncated flag,
  resend, remove user, TOTP QR, console link, save confirmation, terminated tenants, the
  flaky test, branch protection). Group D's P1c-15 triage edits the same file; expect line
  conflicts there and keep both sides' notes. The "deploy version in the answer cache key"
  line is left to P1c-15 (P1b delivered it; verified above).
- `apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` regenerated: `MeOut.operator`,
  `MessageOut.truncated`/`partial`, `InvitationResentOut`, `TerminatedTenantOut`, the new
  routes. Regenerate again after merging Group A's route changes.

### Checks run (last lines, on the branch head before this file)

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | All checks passed! |
| `uv run --directory apps/api ruff format --check .` | 207 files already formatted |
| `uv run --directory apps/api mypy app` | Success: no issues found in 106 source files |
| `uv run --directory apps/api pytest` (PostgreSQL 16, `REQUIRE_DB_TESTS=1`) | 1379 passed, 1 deselected in 134.76s |
| `uv run --directory packages/eval ruff check .` | All checks passed! |
| `uv run --directory packages/eval mypy` | Success: no issues found in 17 source files |
| `uv run --directory packages/eval pytest` | 93 passed in 2.47s |
| `uv run --directory packages/eval python -m eval gate` | **Pass.** |
| `pnpm --dir apps/web gen:api` then `git diff` | schema.d.ts unchanged |
| `pnpm --dir apps/web lint` | All matched files use Prettier code style! |
| `pnpm --dir apps/web typecheck` | exit 0 |
| `pnpm --dir apps/web test` | Tests 116 passed (116) |
| Playwright (preinstalled Chromium) | 18 passed (11.3s) |
| Playwright, the instructions test | 10 passed (one worker); 40 passed (four workers) |
| actionlint 1.7.12 (CI's pinned build) | no findings |
| shellcheck on `deploy.sh` | no findings |
| `deploy.sh --dry-run` here | compose config: ok; digest check stopped: registry did not answer (429) — fail closed |

Baseline before the build: 1348 API tests passed. No API dependency changed, so
`packages/eval/uv.lock` is unchanged.

### Questions for the owner

1. **Removed user's Authentik account.** Removal deactivates it; deleting it needs
   `authentik_core.delete_user` on the provisioner role (blueprint change, re-applied at the
   release). Add the permission and delete the account with the rest, or keep deactivation
   and the manual deletion step?
2. **Register authors.** A user named as proposer or approver in the source or site
   register cannot be removed (`register_author`): today only internal users, and the
   operator and content-role holders are refused anyway. Keep, or blank those references
   (a schema change)?
3. **Failures before the answer starts.** A refusal, a retrieval outage or a model that
   does not open still stores no turn (only the audit event). Keep the question in those
   cases too, with an empty partial answer?
4. **Corpus-only stop before the first citation.** The stored partial answer is then empty
   (the uncited text was never shown and is never stored). Is a question with an empty,
   flagged answer in the history what you want, or should such a turn not be stored?
5. **Digest check in CI.** The dry run asks Docker Hub directly, as the runbook does
   (100 anonymous manifest requests an hour per address). Keep it, or use `--hub-mirror
   mirror.gcr.io` in CI (a mirror can lag a re-pushed tag)?
6. **`--commit` deploys** leave the live tree detached at that commit (and `config/`
   with it), for a rollback. Allow, or deploy only `main`?
7. **Content store copy.** The procedure assumes the volume backup's destination and a 14-day
   retention. Name the destination and the retention to use (it must match what the
   certificate of deletion says about backups).
8. **Eval workflow artifacts.** `eval.yml` still uploads the full run folder (answers) as a
   30-day GitHub artifact, as before this phase. With full outputs kept off the repository,
   upload only the redacted copy?
