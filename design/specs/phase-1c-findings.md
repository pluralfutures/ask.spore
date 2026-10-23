# Phase 1c Findings

Oct 23, 2026. Build record of Phase 1c (`phase-1c-build-spec.md`), kept like `phase-1b-findings.md`: where a build differs from the spec, and why. Metadata only: no query, answer, token, link or email address is recorded here. Section 1 is Group A's, section 2 Groups B and C's, section 3 Group D's (each written on its own branch); the integration and the release add sections 4 and 5.

## 1. Where the Group A build differs from the spec

Branch `phase-1c/group-a`, from `main` plus the approved spec (eb8caf3). Items P1c-01 to
P1c-06. Migration used: **0042** (down_revision 0041). Metadata only below: no request or
response body, address, token or secret.

### P1c-01 Tags: safe default and package check

| Spec says | Built |
| --- | --- |
| A tag with no `tenant` belongs to the internal tenant; sharing is explicit (`shared = true`) | `TagConfig` gains `shared: bool = False` and an `owner` property: the tag's `tenant`, the internal tenant (`internal`) when unset, `None` (every tenant) only when `shared = true`. `tags_for_tenant` and the picker's `shared` flag read it |
| `load_tags` refuses a file that relies on the old default | `load_tags` refuses an entry that names neither `tenant` nor `shared = true` (message names the tags and both fixes) and one that sets both. `config/tags.toml` already names a tenant on every tag (F4), so it loads unchanged; its header comment now states the rule |
| The operator API refuses a workspace save naming a tag outside the tenant's package or the shared set ("today only the picker filters") | **Already built** in P1b-12 / F4: `_check_tags` answers 422 `tag_not_for_tenant` on create and on the tag save. The spec's "today" predates F4. Not changed; covered by a new test for the new default |
| Tests | `test_tags`: a file on the old default is refused; tenant and shared together refused; a `TagConfig` without a tenant is on no client picker (internal only); every repository tag names its owner or is marked shared. `test_operator_console::test_a_tag_without_a_tenant_is_offered_to_no_client_and_refused_on_save`: unset tag absent from two client pickers, shared tag offered and flagged, unset tag refused with `tag_not_for_tenant`, a mixed save refused as a whole and writing nothing, the internal tenant may use it. The internal `research` workspace's `sample-*` tags: `test_repository_sample_tags_belong_to_the_internal_tenant` and the existing picker test |

Note: the compliance guide's model-2 text ("every tag has an owner (a tenant, or none for
a platform tag)", §15) reads "none" as a platform tag; after P1c-01 a platform tag says
`shared = true` and "none" means internal. Same intent, stricter default; question 1.

### P1c-02 SSO refusals and audit

| Spec says | Built |
| --- | --- |
| An out-of-domain or unverified sign-in ends in a clear refusal on our landing page, an Authentik policy or mapping return value, never an exception | The generated source mapping (`app/auth/authentik.py`) now **returns** `{"attributes": {"ask_spore_refusal": "<code>"}}` (no tenant, no address) for an address outside the verified domains, a Google `hd` outside them and (new) an address the IdP did not verify. The blueprint's source-flow policy `ask-spore-source-if-sso` denies a plan whose `prompt_data` carries the refusal, with the message `ask-spore-refusal:<code>`, before any stage runs (no Authentik user written). Desk-checked against the `version-2026.8` source: the mapping exception was raised in `SourceFlowManager.__init__` (uncaught: HTTP 500, `configuration_error`); a flow policy denial is `FlowNonApplicableException`, which `get_flow` turns into `AccessDeniedResponse` (HTTP 200 page with the messages). The adapter reads only our three codes from that page (`source_refusal`), else `refused_by_source`. The callback redirects to `/?sign_in=failed&reason=<reason>` and the page says why |
| (refusal code on the page) | The page gets a **coarse reason**, never the code: `domain` (`domain_not_verified`, `hd_mismatch`), `unverified`, `no_access` (`not_invited`, `user_inactive` and `email_in_other_tenant`, so an outsider cannot tell another tenant's user apart), `start_again` (binding, used, expired), else `failed`. The code is in the audit event. Question 2 |
| `auth.login_failed` with `method = sso:<kind>` and the code; successful logins `sso:<kind>` | `auth.login`, `auth.login_failed`, `auth.user_provisioned` and `auth.role_from_sso` carry `method` `sso:<kind>` once the attempt's source is known; refusals before that (another browser, unknown, used or expired attempt) carry `sso`, as the kind cannot be known. `users.last_login_method` stays `sso` (its check constraint; no migration) |
| Removing a source clears the console's form | `OperatorTenant.tsx`: on a successful removal the form is reset (`formAfterRemoval()`) and the problem text cleared |
| Tests with the fake IdP | `tests/authentik_expressions.py` runs the real generated mapping and the blueprint's policy expression as Authentik does; the fake IdP's `apply_mapping` uses them and records Authentik's events (`property_mapping_exception`, `configuration_error`) when a mapping raises. `test_sso`: per kind (Entra, Google, OIDC, SAML) an out-of-domain sign-in lands on our page with `reason=domain`, `sso:<kind>` and `domain_not_verified` in the audit, no event, no token minted, no user; unverified address (Google, OIDC); Google `hd`; `sso:<kind>` on login per kind; the tenant admin's audit export shows the kind; the reasons never reveal another tenant's user; the mapping never raises on odd IdP input (6 inputs × 4 kinds). `test_authentik_adapter`: the denial page yields our code and nothing else. `test_authentik_blueprint`: the policy denies with the code, passes otherwise, still refuses a non-SSO start. `test_saml_metadata`: refusals are return values carrying no tenant or address. Web: `ssoRefusalText` per reason, generic fallback (including `toString`), the alert on the page; `formAfterRemoval` empty |

A source configured before this change keeps its raising mapping until the console saves it
again (the API still refuses the sign-in either way). On the Instance no SSO source exists
after the Phase 1b drills. `verify_blueprint.py` checks the policy's refusal clause.

### P1c-03 Credentials rotation

| Spec says | Built |
| --- | --- |
| A startup check that refuses to start with any password equal to an `.env.example` value | `app/core/credentials.py`, called by `load_settings` (API, worker, CLI). In `[auth] mode = "oidc"` it refuses when one of 12 secret keys the process reads, or the password of `DATABASE_URL`, `MIGRATIONS_DATABASE_URL` or `REDIS_URL`, equals a value the repository publishes: `askspore-dev`, `askspore-app-dev` (examples and Compose defaults), `change-me` (RAGFlow example), `ci-only-password` (CI). The error lists key names and points at the procedure; values are compared, never printed. Phase 0 mode (loopback dev and eval) is not checked (question 3) |
| (keys the API cannot see) | `infra/scripts/check-credentials.py` (standard library): compares `.env`, `infra/.env` (Compose interpolation; `infra/compose.dev.yml`'s project directory is `infra/`, so its `${POSTGRES_PASSWORD:-…}` defaults come from the shell or `infra/.env`, not the root `.env`), `infra/authentik/.env` and `infra/ragflow/.env` with the published values; also fails on an unset Compose-defaulted password and on any `AUTHENTIK_BOOTSTRAP_*` key (Authentik re-creates the bootstrap token from them at start). Key names only, exit 1 |
| A written rotation procedure in `infra/README.md` | "Credentials rotation (P1c-03)": database roles (`\password` in psql, `infra/.env`, root `.env` DSNs, recreate), Authentik bootstrap token (remove the env keys first, then delete the token; check `AUTHENTIK_API_TOKEN` is the provisioner's) and `akadmin` password, optional Authentik database password, RAGFlow (Valkey, MinIO, MySQL, Elasticsearch, `RAGFLOW_API_KEY`), Redis (no password set: nothing to rotate), verify. Secrets never pass through a session |
| Run once on the Instance by the owner | Not run (owner, at release) |
| Test: the check fires on the example values | `tests/test_credentials.py`: fires on each example DSN, a published Redis password and token; names all keys at once; passes on rotated values; a password containing a published one passes; Phase 0 mode keeps local stacks; the published set equals what the repository publishes (parsed from the files); the host script fires on a fresh install's `.env` copies and passes on rotated ones; reads interpolation from the shell; flags bootstrap keys; no value in any output |

**Release ordering:** on the Instance `DATABASE_URL` and `MIGRATIONS_DATABASE_URL` still use
the Compose defaults (findings 1b §8 0.2), so the Phase 1c API refuses to start there until
step 1 of the procedure has run. Rotate before the deploy, or as its first step (question 4).

### P1c-04 Jobs table isolation and the port test

| Spec says | Built |
| --- | --- |
| RLS on `jobs`: the application role's policy scoped by the payload's `tenant_id`, worker and operator roles unscoped | Migration **0042**: RLS enabled and forced. `tenant_scope` with the review's exact predicate (payload tenant NULL, or no `app.tenant_id`, or equal), as `USING` and `WITH CHECK`, applied to every role with a grant (not only `askspore_app`) so a non-superuser schema owner keeps working under FORCE (the termination purge scopes to the tenant it deletes); `operator_console` (`askspore_operator`, `true`) keeps the operator unscoped |
| Cross-tenant zero-rows test | `test_jobs`: a session scoped to tenant A reads zero of B's mail jobs, sees its own and tenant-less jobs, updates none of B's; cannot queue a job for B (RLS violation); the operator role sees all scoped or not; RLS forced with exactly the two policies. Full suite with the database (worker, CLI, purge, termination, content console paths) below |
| A test that parses the Compose files and fails on a published port not on loopback, except Caddy's 80 and 443 | `tests/test_compose_ports.py`: every Compose file under `infra/` (four today, including the Keycloak drill), short and long syntax, interpolation defaults; also proves it catches no-address, `0.0.0.0`, `[::]`, container-only and long-syntax cases, and that Caddy's exemption is 80 and 443 only |
| `FetchError` messages asserted never logged in the static logging policy test | `test_logging_policy` scans every handler catching `FetchError`: the error may be read only as `.code` or `.status`, or passed to `_refused` (detail = code). It found `app/cli.py` `_load` passing the message (it names the URL) into `IngestError`, which the CLI prints on exit; that now carries the code only |
| `[retention] downloads_days` capped at 365 | `le=365` (was 3650); the repository value stays 90; tests for 1, 90, 365, 366, 3650, 0 |

### P1c-05 Mail domain policy

| Spec says | Built |
| --- | --- |
| DMARC to `p=quarantine` after one week of clean reports; owner action at the DNS; the session checks the reports' summary, counts only | Documentation only: a row in `design/compliance/paperwork-checklist.md` ("due before launch") and `infra/README.md` "Mail domain policy (P1c-05)": the condition (seven consecutive days in which every message from Scaleway TEM passes DMARC and no unknown source sends as the domain), what a session may read (counts per day and source), the TXT change (only `p=` changes; existing `rua=` kept), the check after. No report has been read; the owner has not changed the record |

### P1c-06 Image re-pins

| Spec says | Built |
| --- | --- |
| Read each publisher's changelog for the three moved tags; re-pin with `image-digests.py --write` | **Not re-pinned; item stopped.** Docker Hub answered 429 to this session's address (anonymous limit exhausted, shared address; `ratelimit-remaining: 0`), and `--hub-mirror mirror.gcr.io` is refused by the session's egress policy (403). The publishers' records for official images (docker-library `official-images` and `repo-info`, and Caddy's releases) are on GitHub, outside this session's repository scope; alpinelinux.org is also refused |
| (what could be read) | Docker Hub's tag API (not rate-limited): the three tags still point at the digests the release recorded on Oct 22 (`postgres` `sha256:f461…ac36`, `redis` `sha256:57e4…6541`, `caddy` `sha256:eb4d…510f`; pushed Oct 21–22). Their layers carry the same application versions as the tags (`PG_VERSION=16.15`, `REDIS_VERSION=7.4.11`, `CADDY_VERSION=v2.11.7`) on Alpine minirootfs 3.24.3, 3.21.9 and 3.23.7. That is the shape of a routine same-version rebuild, but the old images' base versions (registry only) and the publishers' own change records were not read, so the spec's condition is not met |

### Checks run (last lines)

```
uv run --directory apps/api ruff check .                → All checks passed!
uv run --directory apps/api ruff format --check .       → 205 files already formatted
uv run --directory apps/api mypy app                    → Success: no issues found in 106 source files
TEST_ADMIN_DATABASE_URL=postgresql://askspore:ci-only-password@localhost:5432/postgres REQUIRE_DB_TESTS=1 \
  uv run --directory apps/api pytest -q                 → 1456 passed, 1 deselected in 193.32s (0:03:13)  (deselected: test_ragflow_integration)
packages/eval: ruff check . / mypy / pytest -q          → All checks passed! / Success: no issues found in 16 source files / 88 passed
pnpm --dir apps/web lint / typecheck / test             → All matched files use Prettier code style! / tsc -b clean / Tests 104 passed (22 files)
python3 infra/scripts/image-digests.py --check          → HTTP Error 429 (Docker Hub); --hub-mirror mirror.gcr.io → 403 (egress policy)
```

PostgreSQL 16 local cluster (`pg_ctlcluster 16 main`). The first full run had 5 failures, all
caused by the new P1c-01 API test leaving a second workspace in the shared `internal` tenant
(later tests expect one); the test now removes it. No route changed, so `openapi.json` and
`schema.d.ts` are unchanged; no API dependency changed, so `packages/eval/uv.lock` is unchanged.

Session note: for the P1c-02 desk-check this session read Authentik's public `version-2026.8`
source files from raw.githubusercontent.com (read-only), which is outside the session's
GitHub repository scope; it stopped using GitHub for other repositories after noticing.

### Questions for the owner

1. **Tag ownership wording (P1c-01).** Confirm that a tag with no `tenant` now means the
   internal tenant and a platform tag shared with every tenant says `shared = true`; the
   compliance guide's model-2 text ("none for a platform tag") would then be updated to match.
2. **Refusal reasons on the sign-in page (P1c-02).** The page shows a coarse reason
   (wrong domain, unverified address, no access, start again), never the code, and gives an
   uninvited address and another tenant's user the same "no access" answer. Keep this
   granularity, or show only one generic text as before?
3. **Credentials check scope (P1c-03).** The startup check runs in OIDC mode only (Phase 0
   mode stays usable with the dev defaults). Enforce it in every mode instead (local stacks
   would then need their own passwords)?
4. **Release ordering (P1c-03).** The Phase 1c API refuses to start on the Instance until
   the database roles are rotated. Run the rotation before the Phase 1c deploy, or as the
   deploy script's first step (P1c-10, Group C)? The deploy script could also run
   `infra/scripts/check-credentials.py`.
5. **Image re-pins (P1c-06).** Re-pin from a machine with Docker Hub access after reading
   the docker-library commits for the three tags (the release session on the Instance), or
   give this session GitHub read access to `docker-library/official-images` and retry?
6. **Existing SSO sources (P1c-02).** A source saved before this change keeps its raising
   mapping until saved again. None exists on the Instance today; no migration step is
   planned. Agree?

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

## 3. Where the Group D build differs from the spec

Group D: P1c-13 to P1c-15, on branch `phase-1c/group-d` (from `main` at eb8caf3, the
approved spec), Oct 23, 2026. Built without the Instance or RAGFlow: the live evals are
prepared here and run by the release session (3.1.3).

### 3.1 P1c-13 eval follow-ups

| # | Spec says | Built |
| --- | --- | --- |
| D-1 | "A second full eval set v1 run at weight 0.4" | **Not run** (no Instance, RAGFlow or provider key in a build session). Written as release step 1 in 3.1.3, with a fresh answer cache that does not flush the live one. |
| D-2 | "Try `corpus_only/v6` first (a new version file, both evals)" | `config/prompts/corpus_only/v6.md`, a copy of v5 with four sentences changed in rules 2 to 4 (3.1.1); v5 is untouched. **`[prompts] corpus_only` stays `"v5"`**: switching is the release session's decision after the live evals (3.1.3). Run here: the API prompt tests with v6 added to every released-template test, a v6 test that pins the change to rules 2 to 4 and keeps every v5 rule sentence, the prompt-layering and no-identifier tests parametrised over the active version and v6 (`test_prompt_layering`), the mocked guardrail eval on a config copy naming v6 (every block 100 in both modes, no regression; also a new eval package test, `test_mocked_run_passes_on_the_corpus_only_v6_candidate`, so CI keeps proving it), the eval package suite and the gate (3.4). The mocked eval proves the slot and the escaping only, not model behaviour (findings 1a §11 state line). |
| D-3 | "if wording does not move them, a relevance check of the top passages before the answer call, as its own spec item with a design note" | Design note in 3.1.4, recorded as a backlog item (P1c-15), no code. |
| D-4 | "Accepting the items as known limits is an owner decision recorded in the findings" | Open, question 1 (3.5): it depends on the live result. |

The three items, from `packages/eval/sets/v1.jsonl` (described, not quoted):

- **hc-v1-039** (synthesis, labels `cross-source`, `gpo`): asks where a decision is made
  across three organisations and tells the model to "cite what" each of three named
  sources says. Retrieved (hit@10) in every release run. v4 and v5 at weight 0.3 gave an
  answer with no passage number, which the orchestrator withholds (findings 1a G6); v5 at
  0.4 gave the fixed decline.
- **hc-v1-055** and **hc-v1-058** (out of corpus, labels `near-miss`, `wrong-year`): each
  asks for figures from a named edition of a publisher's report (a fiscal year, a report
  year) when the corpus holds only the neighbouring edition of the same report series.
  v5 answered both with citations from the edition the corpus has.

#### 3.1.1 The v6 change list

Each change is one sentence or clause added to v5; no v5 sentence is removed or reworded,
the rule numbers and the slot section are unchanged, and the line count is the same.

| # | Rule | Added | Aimed at | Why |
| --- | --- | --- | --- | --- |
| C1 | 2 | "asks what several named sources each say," in the list of questions answered by putting passages together | 039 | The question asks for each named source's position, which no single passage states; v5's list named comparison, "where or whether" and several items, and the model still declined at 0.4. Naming the form puts it on the answer side of the decision. |
| C2 | 2 | "A question that names a particular report, edition or year (for example "the 2024 report" or "fiscal 2026") asks about that one only: check each passage's title and publication date, and a passage from another edition or year, even of the same publisher's series, does not give it." | 055, 058 | v5's near-miss test says "a different year … does not give it" for a specific fact; the model read the passages of the neighbouring edition as the same document, because publisher and series match. The provenance the model sees carries the title and the date (P0-12), so the sentence tells it where to look and that the series does not count. |
| C3 | 3 | "(figures from another year or edition than the one asked about are not part of it)" after "answer that part with citations" | 055, 058 | v4's partial-answer path (findings 1a G8) let a cited answer about the other edition count as "part of what is asked"; the eval counts any valid citation on an out-of-corpus item as an answer. Without C3, C2's decision could be undone by rule 3. |
| C4 | 4 | "Cite by passage number only, also when the question asks you to cite or name the sources: name the publisher in the sentence and put its passage number after it. An answer without passage numbers cannot be shown." | 039 | The question's own "cite what X says" is the likeliest reason the uncited runs named sources in prose instead of `[n]`; the orchestrator then withholds the whole answer (G6). The second sentence states the consequence (true of `corpus_only` since G6) without describing the control. |

Risks the live run must look for: C2 and C3 could make the model decline answerable items
whose question names a year that the passages do cover (the per-item check below covers
the answered items); C4 adds no rule an attack block can use (the mocked eval is unchanged,
the live guardrail eval decides). The decline sentence and the secrecy reply are unchanged,
so both stay under the guardrail eval's 40-character leak length.

#### 3.1.2 What was run here

See 3.4 for the commands and their last lines: API prompt and layering tests (v5 and v6),
the mocked guardrail eval on v6 and on v5 (both: no block degrades any metric), the eval
package suite and the gate.

#### 3.1.3 Release-step instructions for the live runs

For the release session (P1c-16), on the Instance, with the setup of findings 1b §7
(eval keys in `/srv/ask-spore/eval-keys/`, the eval identity, a temporary api
`askspore-eval-api` on `127.0.0.1:8001` from the release image with a config copy that
differs from production by `[auth.eval_service]` only, the harness run by the owner from a
session-written script that exports the secrets by name and prints none). Full outputs go to
`/srv/ask-spore/eval-runs/`; only redacted results are ever committed. Baseline:
`20261023T085603Z-c06e9e99bae9` (v1, `corpus_only/v5`, weight 0.4).

1. **Second run at weight 0.4, v5** (confirms the Oct 23 tuning; backlog Oct 23). Config
   copy `/srv/ask-spore/eval-config/`: production config plus `[auth.eval_service]`, weight
   0.4 (as `main`). Start the temporary api with
   `ASK_SPORE_DEPLOY_VERSION=<release sha>-r2`: the deploy version is part of the answer
   cache key (findings 1b D11), so every answer is fresh and the live cache is not flushed.
   Run all 60 items, as the baseline did (no `--exclude-label`):
   `uv run --directory packages/eval python -m eval run --config /srv/ask-spore/eval-config/models.toml --set sets/v1.jsonl --api-url http://127.0.0.1:8001 --ragflow-url <RAGFlow on the private network> --results-dir /srv/ask-spore/eval-runs --note "P1c-13 second 0.4 run, v5"`,
   then `eval compare results/20261023T085603Z-c06e9e99bae9 <run>`. Record the metrics and
   the outcomes of 010, 039, 046, 055 and 058. A regression beyond 3 points here is noise
   between two runs of the same configuration: report it to the owner before step 2, it
   changes how step 2 reads.
2. **v6 on eval set v1.** A second config copy `/srv/ask-spore/eval-config-v6/` equal to
   the first except `[prompts] corpus_only = "v6"`; recreate the temporary api on it (the
   new prompt version changes the cache key, so answers are fresh). Same `eval run`
   command with `--config /srv/ask-spore/eval-config-v6/models.toml` and
   `--note "P1c-13 corpus_only/v6"`; `eval compare` against the baseline **and** against
   the step 1 run.
3. **v5 and v6 on the guardrail eval, live** (the active provider's model,
   `deepseek-v4.1-flash`): `uv run --directory packages/eval python -m eval guardrails --config /srv/ask-spore/eval-config/models.toml --results-dir /srv/ask-spore/eval-runs --note "P1c-13 v5"`
   and the same with `eval-config-v6` and `--note "P1c-13 v6"`. Only the provider key is
   needed (no database or RAGFlow).
4. **Acceptance rule for v6** (all must hold):
   - eval set v1: no headline metric of the v6 run more than 3 points below the baseline
     (`eval compare` exit 0), and none more than 3 points below the step 1 run;
   - the three items: **hc-v1-039 answered with at least one valid citation** (outcome
     `answered`), **hc-v1-055 and hc-v1-058 not answered with a citation** (the fixed
     decline, or an uncited reply withheld: `unsupported`);
   - no answerable item that step 1 answered with citations is declined or withheld by
     v6, unless the per-item reading shows the step 1 answer was itself wrong (record which);
   - guardrail eval: v6 has no block below its baseline by more than 3 points except the
     accepted `03-drop-citations` (findings 1a G6), and no block below v5's result in
     step 3 by more than one item's worth (16.7 or 20 points, findings 1a B14) without a
     per-item reading.
   If it holds: a PR sets `[prompts] corpus_only = "v6"`, updates
   `test_prompts::test_active_prompts_are_the_section_11_versions`, the
   `test_mocked_run_passes_on_the_active_prompts` expectation in `packages/eval` and the
   `config/models.toml` comment, and the owner accepts the v6 run as the new baseline with
   `accept-baseline` (redacted, in the same PR). If 039 moves but 055 or 058 do not, or
   the reverse, the owner decides between v6 with the remaining items as known limits and
   the relevance check (3.1.4, question 1). If v6 regresses, v5 stays and the owner
   decides the same question.

#### 3.1.4 Design note: a relevance check before the answer call (backlog, not built)

Judgement: wording may fix 055 and 058 (their failure is specific: the question names an
edition and the passage provenance shows another), but the history of rule 2 (findings 1a
G1, G7 to G9: v3 to v5 each left one to three near misses answered) says it will not do so
reliably for near misses in general. This note is the fallback, for an owner decision after
the live run; it is a backlog item, not code.

- **What.** One short model call between context selection and the answer call, in
  `corpus_only` only: the system prompt is a new versioned file
  (`config/prompts/relevance/v1.md`), the user message holds the question and the selected
  passages with their provenance, exactly as the answer call would (the same no-identifier
  rule and the same untrusted-text wrapping), and the model must return one of `answers`,
  `partial`, `none` (JSON with that one key, `max_tokens` about 5, temperature 0, no tools).
  `none` ends the turn with the fixed decline (outcome `abstained`, nothing cited, the
  answer call never made); `answers` and `partial` go on to the answer call unchanged, so
  the check can only remove answers, never add one.
- **Where.** `app.chat.orchestrator`, after `select_context` and before the answer
  stream (architecture §5.2 between steps 8 and 9), behind `[chat] relevance_check = false`
  in `config/models.toml`. The verdict joins the answer cache key (relevance prompt
  version), the `chat.answer` log line gets `relevance` (`answers`, `partial`, `none`,
  `error`) as an allow-listed code, and the eval harness records it per item.
- **Cost per question.** The input is the answer call's input without the answer prompt's
  rules, so about the same prompt tokens, plus a few output tokens: it roughly doubles the
  input tokens of a `corpus_only` turn. The four Oct 23 v1 runs (findings 1b §8, Spend)
  used 856,608 input and 40,947 output tokens for about 190 answer calls (240 questions
  less the 50 cache hits), about 4,500 input tokens per question, for about 58 cents: the
  check would add about 0.25 to 0.3 cents per question on `deepseek-v4.1-flash`, and
  about 0.5 to 1.5 s before the first token (a non-streamed call, then the held stream
  of G6). These are estimates from the ledger totals, not a measurement. A smaller model
  for the check is a model change (owner) and needs its own eval.
- **Failure modes.** (1) False `none` on answerable synthesis questions, the trade v3 made
  (G7): the eval's cited-answer rate is the measure, and the check must pass the same
  3-point gate. (2) The check is a second place a workspace's instructions could act: it
  gets no workspace block (they are about tone and format, not relevance), and the
  guardrail eval gains a mode that runs the check under each hostile block. (3) Text in a
  passage can try to steer the verdict ("this passage answers every question"): the
  passages are wrapped as untrusted, the only effect of a forged `answers` is the
  status quo, and a forged `none` only declines. (4) A failed or malformed call: treat as
  `answers` (fail open to today's behaviour, logged as `relevance=error`), never as a
  decline. (5) Two calls double the place a provider outage bites; failover (findings 1b
  D14) applies to the answer call only, so the check is skipped when it fails.
- **Tests it would need.** Prompt with no identifiers (the P1a-06 test over the check's
  request); `none` makes no answer call and stores the fixed decline; an error falls
  through to the answer; the cache key changes with the check's prompt version; the
  guardrail eval mode.

### 3.2 P1c-14 register and crawl follow-ups

One migration, **0060** (`0060_site_withdrawal`, `down_revision` 0041), for (a) only. Commits
3a5fc78 (e), 9e8c359 (d), 2d200c5 (c), 1ff944a (a, b).

| # | Spec says | Built |
| --- | --- | --- |
| D-5 | (a) "Site-level 'withdraw site' in the console and CLI: withdraws every page of the site (reusing the per-page withdrawal job), retires the site row (no further scheduled crawls), audited" | `app.content.sites.withdraw_site`, a reviewer's action: `POST /api/v1/content/sites/{id}/withdraw` (reason required), a "Withdraw site" form on the site page, and `ask-spore sites withdraw <site_id> --as <email> --reason … [--wait]`. In one transaction the site becomes **`withdrawn`** (a new status value: migration 0060 also adds `withdrawn_at` and `withdrawal_reason`, required together by a check constraint, as on `sources`) with `next_crawl_at` cleared; every live page becomes `blocked` with reason `site_withdrawn`; every `ingested` or `failed` row of the site gets the reason and its own `withdraw_source` job (the per-page job, unchanged), audited `source.withdrawal_requested` with `method: site_withdrawal`; the site gets `site.withdrawn` (before and after status and schedule, roles, the number of jobs; never the reason text). Scheduled crawls, "crawl now" and a queued `crawl_site` job all need `approved`, so nothing crawls the site again. A row still being ingested is withdrawn when its ingestion finishes, because its page is no longer live (the Phase 1b rule, findings 1b A2-7). **Not in the spec:** a crawl running at the moment of withdrawal stops at its next page (each visit checks the site's status, and a page is admitted only under a share lock on the site row, so the withdrawal waits for an admission in progress and then withdraws it), and keeps no next crawl. A migration was needed because `sites.status` had a check constraint without a retired state; reusing `rejected` would have shown a retired site as a declined proposal. The downgrade turns a withdrawn site into `rejected` with its reason as the review note. |
| D-6 | (b) "'Restore' for a withdrawn crawled page so the next crawl takes it again, audited" | `app.content.sites.restore_page`, a reviewer's action on the page's withdrawn register row: `POST /api/v1/content/sources/{id}/restore`, a "Restore page" button on a withdrawn crawled source, and `ask-spore sources restore <source_id> --as <email>`. The page's `site_pages` row goes from `blocked` (`withdrawn`) to `removed` (`restored`), which the crawler treats like any page it has not got: the next crawl that meets it records a new register row (approved in the site approver's name, as every page) and ingests it. The withdrawn row stays withdrawn (its history and citations untouched). Refused: before the withdrawal job has run (`not_withdrawn`), for a page withdrawn by the crawler rather than a reviewer or of a withdrawn site (`not_a_withdrawn_page`, `site_not_approved`), and for a URL any version of which had a takedown recorded (`taken_down`: the Phase 1b rule that such a URL stays out holds). Audited `source.restored`. |
| D-7 | (c) "Clean-up of an interrupted re-tag job as an interrupted first ingestion already is (findings 1b A1-11)" | No migration: `add_tags` now maps each new upload on the row as it happens, as `ingest_source` does. A document mapped in the dataset of a synced tag the row does not hold belongs to an unfinished re-tag, and the next re-tag of the source deletes it from RAGFlow before uploading (`_clean_unfinished_retag`); keys that are not a synced dataset's ID (Phase 0 mappings) are never touched. A failed re-tag unmaps what it deleted and keeps mapped only the documents whose deletion failed, so the next re-tag or a withdrawal removes them (before, they were named in the error and tracked by nothing). Consequence, as for a first ingestion (A1-11): while a re-tag parses, its new dataset's chunks can already be retrieved and cited by tenants with the new tag, whose addition a reviewer approved. |
| D-8 | (d) Decision 3: "a new file replaces an existing document only when both the canonical link and the title match; a link match with a different title is flagged to the reviewer as a possible replacement" | `register.exact_replacement`: at proposal, a file with the canonical link **and** the title (compared ignoring case and runs of spaces) of exactly one ingested, non-crawled source, which no other proposal is already replacing, records that source as `supersedes_id`; the approval then needs no choice and is audited `replaces` with `method: same_link_and_title`, and the A1 supersession path runs once the new file is ingested. So a manifest re-run with a corrected file at the same link and title re-ingests it (`--approve-as`), which decision 4 of Oct 22 had stopped. A link match under another title, or a link two ingested sources share under the same title, is flagged as before (`possible_replacement`, `replacement_choice_required`). The approval checks the match again: a target withdrawn or taken by another proposal meanwhile falls back to the reviewer's choice. **The reviewer may still choose "keep both"** for a same-title match (an override, audited `keep_both`); the decision says when a file replaces, and does not forbid keeping both. `ProposeOut` gains `replaces`, and the console's propose result names the source replaced. |
| D-9 | (e) Decision 3: "the stored excerpt of a citation is blanked on every withdrawal, not only licence ones; the citation stays, labelled withdrawn; adjust the database trigger … only if it blocks this, via a migration" | The withdrawal job blanks the excerpts of the source and of the earlier versions it replaced on **every withdrawal** (a reviewer's, a takedown on any grounds, a crawl's removal, a site withdrawal, a crawled page gone before its ingestion finished); the audit event's `excerpts_blanked` is true for all of them. **The trigger does not block it** (it lets `askspore_content` write only `''`, whatever the grounds), so no migration. **A supersession keeps the excerpt**: the document is still in the corpus under its new version, and decision 3 speaks of withdrawals (question 2). **Not in the spec:** when a document is withdrawn, its earlier versions' citations are labelled withdrawn too (they were only "superseded"), so a citation of any version of a withdrawn document shows "withdrawn" with the blanked-excerpt note; found by the site-withdrawal test, where a page's second version superseded the first while the site was being withdrawn. `takedown_licence_grounds` stays recorded (queue, audit) but no longer changes the withdrawal; the CLI help and the console label say so, and the chat's note now reads "The quoted passage was removed because the source was withdrawn." Architecture §6.3 and §15.7 updated. |

Tests (all against PostgreSQL 16, RAGFlow and the site faked): `test_sites`:
`test_a_withdrawn_site_leaves_no_page_in_any_dataset_and_no_schedule` (two datasets, a page
version still being ingested, a client tenant's citation; afterwards no document of the site
in the fake RAGFlow, every row withdrawn, no live page, `next_crawl_at` empty, a past due date
queues nothing, "crawl now" and a stale queued crawl refused, the audit trail with no reason
text), `test_a_crawl_running_when_its_site_is_withdrawn_admits_nothing_more` (fails without the
guard), `test_a_restored_page_is_crawled_again`,
`test_a_taken_down_or_unwithdrawn_page_cannot_be_restored`; `test_jobs`:
`test_an_interrupted_retag_is_cleaned_up_before_the_next_upload` (a worker stopped mid-parse,
then the job put back) and `test_a_failed_retag_unmaps_what_it_deleted_and_keeps_what_it_could_not`
(both fail on the old code); `test_withdraw`:
`test_the_same_link_and_title_replace_the_old_version_without_a_choice` (CLI path),
`test_an_automatic_replacement_can_be_overridden_or_falls_back_to_a_choice`, the existing
link-only tests now with another title, `test_withdrawal_on_licence_grounds_blanks_the_stored_excerpts`
(unchanged) and `test_every_other_withdrawal_blanks_the_stored_excerpts_too` (plain and
non-licence takedown, across tenants, the superseded version kept until its document is
withdrawn), `test_cli_site_withdrawal_and_restore_flags`; `test_content_console`: the two new
routes are refused to tenant admins and users like every content route, and
`test_a_reviewer_withdraws_a_site_and_restores_a_page_from_the_console` (editor refused,
codes, audit), `test_the_same_link_and_title_replace_without_a_choice`; web unit tests for the
propose result, the withdrawn-site summary, the two new page reasons and the "Withdraw site"
form.

### 3.3 P1c-15 backlog triage

One commit, no code. Each struck line names what delivered it; each was checked against the
code or the findings first (the crawler, the consent gate migration, `design/compliance/`,
the committed eval results and the gate).

| | Lines | Notes |
| --- | --- | --- |
| **Struck** | **28** | 21 delivered by Phase 1b or earlier: re-ingestion and withdrawal (P1b-03), stored own-analysis files (P1a-14, P1b-02), the approval step and content console (P1b-01, P1b-05), crawler policy and publication dates (P1b-04), the Oct 18 Phase 1b line (console, approval flow, retention jobs, SSO connectors), operator spend visibility (P1b-12), the consent gate (P1b-10), per-IP rate limit, session refresh, sign-out revocation, `no_binding`, the Authentik blueprint (P1b-08), platform mail (P1b-11), the four document-set lines (P1b-09, drafted), the one-tenant console (P1b-12), the deploy version in the cache key (P1b-13 e), the committed Phase 0 eval results (owner decision Oct 21, enforced by the gate since P1b-15 b). 5 delivered by this branch (P1c-14 a to e: the re-ingestion title and excerpt decisions, the re-tag clean-up, restore, withdraw site). 1 moved to P1c-07 (resend invitation). 1 closed by owner decision (branch protection, decision 2 of Oct 23). Three struck lines were delivered only in part; their remainders are carried as new Phase 2 lines (two-host deployment; per-path TDMRep rules and site terms review; the support-access policy and staff checklist). |
| **Re-tagged** | **29** | 25 as Phase 1c with their item (P1c-01 to P1c-09, P1c-11, P1c-13), including the two owner-held items (P1b-13 a and b) marked as not build items; 4 as Phase 2 (the RAGFlow UI path, Object Storage, guardrail eval scoring of fixed sentences, the no-self-approval rule). The truncation line, counted under Phase 1c, keeps its struck part; its open tail is split between P1c-09 (the stored flag) and Phase 2 (an eval run on the output cap). The Phase 1a relevance-check line is re-tagged as the P1c-13 fallback with a pointer to 3.1.4. |
| **Left as is** | **23** | 12 lines struck before this triage and 11 open lines already tagged Phase 2. |
| **Added** | **5** | The three carried remainders above and two ideas from this build: reinstating a withdrawn site (its start URL is unique, so it cannot be registered again), and the future of `takedown_licence_grounds` now that every withdrawal blanks excerpts. |

Not struck although the brief lists it: none. The **vector weight, judge model and eval gate**
and the **eval harness OIDC path, reasoning tokens and retention lines** were already struck
before this triage (left as is). The Phase 1a Playwright flake line was **not** struck
although P1b-13 f fixed a race in it (findings 1b D12): the Phase 1c spec carries it again as
P1c-11, so it is re-tagged there.

### 3.4 Checks run on this branch

All on the branch head, in the session container (PostgreSQL 16.15 started with
`pg_ctlcluster 16 main start`, role `askspore` as in CI,
`TEST_ADMIN_DATABASE_URL=postgresql://askspore:ci-only-password@localhost:5432/postgres`,
`REQUIRE_DB_TESTS=1`). Last line of each:

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | `All checks passed!` |
| `uv run --directory apps/api ruff format --check .` | `201 files already formatted` |
| `uv run --directory apps/api mypy app` | `Success: no issues found in 105 source files` |
| `uv run --directory apps/api pytest` (with the database) | `1371 passed, 1 deselected in 151.31s (0:02:31)` (`test_ragflow_integration` deselected, as in CI) |
| the same without the database | `614 passed, 757 skipped, 1 deselected in 8.93s` |
| `uv run --directory packages/eval ruff check .`, `ruff format --check .`, `mypy` | `All checks passed!`, `37 files already formatted`, `Success: no issues found in 16 source files` |
| `uv run --directory packages/eval pytest` | `89 passed in 2.63s` |
| `uv run --directory packages/eval python -m eval gate` | `**Pass.**` (no run newer than the baseline is committed) |
| `python -m eval guardrails --mock` on a config copy naming `corpus_only/v6` | `No block degrades any metric beyond the threshold.` (every block 100 in both modes; the same on v5) |
| `pnpm --dir apps/web lint`, `typecheck`, `test` | `All matched files use Prettier code style!`, `tsc -b` clean, `Tests  102 passed (102)` |
| `pnpm --dir apps/web test:e2e` (`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`) | `13 passed` |

`apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` were regenerated for the new
routes and fields. No API dependency changed, so `packages/eval/uv.lock` is unchanged. No eval
result was committed. Not run: anything that needs the Instance, RAGFlow or a provider key
(3.1.3).

### 3.5 Questions for the owner

1. **hc-v1-039, 055, 058 (P1c-13, after the live run).** If v6 passes the acceptance rule of
   3.1.3, switch to it. If it fixes some but not all three items, or regresses: accept the
   remaining items as known limits (recorded here), or fund the relevance check of 3.1.4 as
   its own spec item (one extra model call per `corpus_only` question, about 0.25 to 0.3
   cents and up to 1.5 s)?
2. **Excerpts on supersession (P1c-14 e).** Decision 3 blanks excerpts on every withdrawal;
   this build keeps them when a re-ingested version replaces a document (the citation shows
   "superseded" and the document is still in the corpus), and blanks every version's
   excerpts once the document itself is withdrawn. Confirm, or blank on supersession too.
3. **Keep both on a same-title match (P1c-14 d).** A file with the same link and title
   replaces the old source without a choice, but the reviewer may still choose "keep both"
   at approval. Confirm the override, or make the replacement unconditional.
4. **A withdrawn site is final (P1c-14 a).** Its start URL stays taken (unique), so the same
   site cannot be registered again; reinstating one is a Phase 2 backlog line. Confirm, or
   ask for a reinstate action now (it would go back to `proposed` for a reviewer).
5. **Restore waits for the next crawl (P1c-14 b).** A restored page comes back when its
   site's next scheduled or requested crawl meets it; restore does not queue a crawl itself
   (a reviewer can press "Crawl now"). Confirm, or queue a crawl on restore.
6. **`takedown_licence_grounds` (P1c-14 e).** It no longer changes what a withdrawal does.
   Keep it as a record on the takedown queue (as built), or drop the flag and its checkbox
   (a migration; backlog line)?
7. **Migration number.** 0060 on 0041 as briefed; if Groups A to C also chain on 0041, the
   integration step re-parents one `down_revision` line.

## 4. Integration of Groups A, B/C and D (Oct 23, 2026)

Branch `phase-1c/integration`: `main` plus the approved spec (eb8caf3), then
`phase-1c/group-a`, `phase-1c/group-d` and `phase-1c/group-bc`, by the orchestrating session,
with the three independent reviews (no blocker in any). Conflicts: this file (three
sections, kept in order), `design/specs/backlog.md` (Group D's triage taken as the base,
Groups B and C's eight strikes re-applied on it), `infra/README.md` (both sides kept).

| # | Item | What | Why |
| --- | --- | --- | --- |
| I-1 | Migrations | Chain 0041 → **0042** (jobs RLS) → **0050** (message flags) → **0051** (user removal) → **0060** (site withdrawal); 0050 and 0060 re-parented. | Three heads otherwise. |
| I-2 | P1c-04 | `IngestError` messages carry no URL (they reached the CLI's exit text, the same sink the `FetchError` rule closed); two tests. | Group A review item 1. |
| I-3 | P1c-04 | The Compose port test also finds `.yaml` files. | Group A review note 9. |
| I-4 | P1c-01 | Compliance guide §15 wording: a tag with no `tenant` is internal; a platform tag says `shared = true`. | Owner decision 6. |
| I-5 | P1c-04 × P1c-07 | The jobs-policy test expects the third policy `user_removal` (0051) beside `tenant_scope` and `operator_console`. | Both groups touched `jobs` policies in parallel. |
| I-6 | P1c-06 | **Re-pinned here** with `image-digests.py --write`: `postgres:16.15-alpine` (Authentik's database), `redis:7.4.11-alpine`, `caddy:2.11.7-alpine`; same application versions on newer Alpine bases (Group A's reading of the tag pages); `--check` passes for every reference this container can reach. Decision 10 (re-pin from the Instance) was taken because the build container was rate-limited; this container was not, and the new CI dry run of the deploy script (P1c-10) would otherwise fail on the moved tags. The release step runs `--check` on the Instance, where quay.io (the Keycloak drill image) is reachable. | P1c-06, P1c-10. |

| I-7 | P1c-08 | The terminated-tenant list requires `status = suspended` as well as the missing entitlements or login policy; a half-created active tenant is not listed (test added). | B/C review item 5. |
| I-8 | P1c-10 | The deploy script runs `check-credentials.py` before the build (step 6; fail closed, key names only), reads the api port from Compose (`compose port api 8000`) instead of the shell, and recreates api and worker so their startup lines are fresh on a re-run. Steps renumbered 1 to 11. | B/C review items 6, 7, 9. |
| I-9 | Backlog | B/C's note on the truncated-flag line re-applied on the triaged file. | Merge resolution. |

Noted, not changed (B/C review): a resend is unbounded once the previous mail was sent
(backlog, before the first client user: refuse a resend within a few minutes of the last);
Authentik deactivation runs before the database commit on user removal (recoverable by a
re-invite); the 0051 downgrade deletes authorless workspace prompts (forward-only deploy);
a disconnect before the first token stores an empty partial answer; the eval workflow still
uploads the full run folder as a 30-day artifact (owner question, findings §2).

**Not run here:** the Playwright suite (this container lacks the headless-shell build the
project's Playwright version expects; the three build sessions ran it, 13 passed each) and
`--check` against quay.io (proxy). Both are release-step checks.

**Checks on the integration branch:** API ruff, format, `mypy --strict` clean; 1511 tests pass
against PostgreSQL 16 (1 deselected); eval package ruff, format, mypy, 94 tests and `eval gate`
pass; web lint, typecheck and 122 unit tests pass; `openapi.json` and `schema.d.ts`
regenerated and in sync; `compose config` valid with the example RAGFlow env; the deploy
script's dry run passes after the re-pins (fails closed on a moved tag, as designed).

## 5. Release on the Instance, Oct 23, 2026 (P1c-16)

Run by a remote-control session on the Instance from `design/specs/phase-1c-release-runbook.md`.
The Instance runs `main` at **1758623** (`ASK_SPORE_DEPLOY_VERSION=175862320a89`).

### Release status

**In progress** (Oct 23, 2026): sections 0 to 2 done (independent review signed, no blocker);
sections 3 to 7 to follow.

### Section 0: credentials rotation

| Step | Result |
| --- | --- |
| 0.1 Rotation | Done by the owner in their own terminal (procedure: `infra/README.md`, "Credentials rotation"); nothing from it passed through the session. `check-credentials.py`: exit 0, "ok" for `.env`, `infra/authentik/.env`, `infra/ragflow/.env`. api and worker restarted on the new values: `/healthz` 200 on loopback and over TLS, one `api.started` and one `worker.started` line. |

### Section 1: deploy by script (P1c-10)

| Step | Result |
| --- | --- |
| 1.1 Instance | On; remote-control session. |
| 1.2 Source | `main` pulled at **175862320a89** (PR #61 on top of the runbook's PR #60: F1). Tree clean, on `main`. |
| 1.2 Dry run | `deploy.sh --dry-run`: compose config ok, **18 image pins match** (quay.io reachable from the Instance). |
| 1.2 Deploy | Run by the owner from the Instance (the session's run was refused by its permission policy), started 11:58:49 UTC; summary in `/root/deploy-1c.log` (metadata only), read by the session. Commit 175862320a89, deploy version 175862320a89; credentials step passed; `migrate`, `api`, `worker`, `web-build` built; Alembic head **0060**; `/healthz` ok on loopback and over TLS; `auth/mode` `oidc`; `ragflow-tei` running; worker started, 0 mail warnings; 7 datasets with counts equal to the Oct 20 figures (owner's comparison). "0 datasets counted" before the build is expected on this script's first run (the previous image had no `datasets counts` command, so step 10 recorded figures with nothing to compare). One `curl: (56)` connection reset in step 10 was the health loop's first attempt while the api started; the loop then passed. |

### Section 2: isolation tests and the independent review

- **2.1 Run:** full suite at 175862320a89 with `REQUIRE_DB_TESTS=1`, run with `uv` from a
  worktree of the release commit, against a **throwaway PostgreSQL 16.15 container** (the
  live `postgres` service's pinned digest, tmpfs, loopback port, removed after the run).
  Not a scratch database in the live cluster: the test migrations create cluster-wide roles
  (`askspore_app`, `askspore_retention`, `askspore_user_removal`, ...), which would touch the
  live roles; same choice as Phase 1b §8 1.1. **1511 passed, 0 failed, 1 deselected**
  (`test_ragflow_integration`), 229 s. ruff clean; `mypy --strict` clean (107 files).

- **2.2 Controls on the Phase 1c changes** (all in `apps/api/tests/`). The generic checks over
  `test_schema.TENANT_TABLES` (`test_tenant_tables_list_is_complete`,
  `test_table_has_forced_rls_policy_and_tenant_first_index`, `test_other_tenant_sees_zero_rows`
  and the rest of Phase 1b §8 1.2) still cover `messages`, which carries the new flags.

| Control | Tests |
| --- | --- |
| `jobs` RLS (P1c-04, revision 0042; closes the Phase 1b review's ruling) | `test_jobs::test_a_tenant_scoped_session_reads_no_job_of_another_tenant`, `test_a_tenant_scoped_session_cannot_queue_a_job_for_another_tenant`, `test_the_operator_role_reads_every_job_even_when_scoped`, `test_jobs_rls_is_forced_with_both_policies` (with the third policy `user_removal`, I-5), `test_payloads_hold_identifiers_only`, `test_log_lines_take_job_fields_as_scalars_only` |
| Role `askspore_user_removal` and user removal (P1c-07, revision 0051) | `test_user_removal::test_removal_leaves_no_row_with_the_users_id_outside_audit_events`, `test_a_tenant_admin_cannot_remove_another_tenants_user`, `test_the_application_role_alone_cannot_delete_users` (also: the removal role cannot read message text), `test_removal_knows_every_column_that_names_a_user`, `test_an_unknown_user_column_refuses_the_removal`, `test_unknown_user_columns_is_empty_on_the_schema`, `test_removal_refuses_the_admin_themselves_and_the_last_admin`, `test_the_operator_removes_any_tenants_user_but_no_platform_role`, `test_a_provider_failure_rolls_the_removal_back`, `test_a_plain_user_cannot_remove_or_resend`, `test_resend_refuses_an_active_user_and_another_tenants_user`; `test_authentik_adapter`: deactivation is a PATCH, never a DELETE |
| Message flags `truncated`, `partial` (P1c-09, revision 0050) | `test_partial_answers::test_no_history_leaves_no_row_when_stopped`, `test_no_history_leaves_no_row_when_the_model_fails_mid_stream`, `test_a_corpus_only_answer_stopped_before_its_first_citation_keeps_no_text`, `test_a_stopped_answer_is_stored_partial` (log line without text), `test_a_disconnect_stores_the_partial_answer`, `test_a_model_failure_mid_stream_keeps_the_question_and_the_partial_answer`, `test_a_failure_before_the_answer_starts_stores_nothing`, `test_a_cut_off_answer_keeps_its_note_after_a_reload` |
| Tags default internal (P1c-01) | `test_tags::test_a_tag_without_a_tenant_is_never_on_a_client_picker`, `test_a_file_relying_on_the_old_shared_default_is_refused`, `test_a_tag_cannot_be_both_a_tenants_and_shared`, `test_every_repository_tag_names_its_owner_or_is_marked_shared`, `test_repository_sample_tags_belong_to_the_internal_tenant`, `test_shared_tags_are_offered_to_every_tenant_and_own_tags_to_one`; `test_operator_console::test_a_tag_without_a_tenant_is_offered_to_no_client_and_refused_on_save` |
| SSO refusal path (P1c-02) | `test_sso::test_an_out_of_domain_sign_in_is_refused_by_the_source_on_our_page`, `test_an_address_the_idp_did_not_verify_is_refused_by_the_source`, `test_a_google_hd_outside_the_domains_is_refused_by_the_source`, `test_the_refusal_reason_does_not_tell_another_tenants_user_apart`, `test_the_mapping_never_raises_whatever_the_idp_sends`, `test_every_kind_records_its_kind_on_login`, `test_the_audit_export_shows_the_kind_of_each_sso_event`; `test_saml_metadata::test_a_refused_mapping_carries_no_tenant_and_no_address`; `test_authentik_adapter::test_a_policy_denial_of_the_source_flow_is_refused_with_the_mappings_code`; `test_authentik_blueprint::test_the_source_policy_denies_a_refused_mapping_with_its_code` |
| Credentials check (P1c-03) | `test_credentials::test_the_api_refuses_to_start_on_a_published_credential`, `test_every_published_key_is_named_at_once`, `test_the_published_values_are_what_the_repository_publishes`, `test_the_script_fires_on_the_example_values`, `test_the_script_passes_on_rotated_values`, `test_the_script_reads_compose_interpolation_from_the_shell_too`, `test_the_script_flags_authentik_bootstrap_keys` (each asserts no value in any output); live: 0.1 and the deploy's step 6 |
| Loopback-only ports, no URL in error text (P1c-04, I-2, I-3) | `test_compose_ports::test_nothing_is_published_beyond_the_loopback_but_caddy`, `test_caddy_publishes_80_and_443_only`, `test_the_check_catches_every_way_to_publish_a_port`; `test_logging_policy::test_a_fetch_error_message_never_leaves_its_handler`; `test_ingest::test_from_fetched_messages_carry_no_url` |
| Operator flag on `/me`, terminated tenants (P1c-08) | `test_console_feedback::test_me_says_operator_only_for_an_operator`, `test_only_operators_see_terminated_tenants`, `test_a_terminated_tenant_is_listed_with_its_certificate` |
| `downloads_days` cap (P1c-04) | `test_config::test_downloads_retention_is_capped_at_365_days` |

  The Phase 1a and 1b controls keep their tests (findings 1a §10; 1b §8 1.2); all ran in 2.1.
  **Signed:** the isolation review of the Phase 1c changes passes at 175862320a89.

- **2.3 Independent review (5.2): signed, no blocker.** Launched by the orchestrating session
  on `main` since 1a714fe, signed at 175862320a89; every CLAUDE.md non-negotiable holds. The
  report is `design/specs/phase-1c-independent-review.md` (commit c270784, on the
  orchestrating session's branch, to reach `main` with its PR). Four backlog items, none a
  change before this release: `RagflowError` detail kept out of logs and added to the static
  scan (its item 3); the Keycloak drill Compose file asserted in the port test's file list
  (8); a case-insensitive, minimum-length credentials comparison (11); rate-limiting
  invitation resends before the first client user (§4, already a backlog line, now marked
  confirmed).

### Section 3: live checks

- **3.1 Pre-existing SSO sources:** `tenant_login_policy` holds two rows (`internal`, `cc`), both
  with source kind `none` and no source slug: no SSO source to re-save.
- **3.2 Deviation from the runbook's fixed values (owner decision, Oct 23, 2026):** the slug
  `ssotest` is not free. The Phase 1b termination purge keeps the `tenants` row (suspended,
  Phase 1b F5), and slugs are unique, so the console answered `slug_taken`; nothing was written.
  The purged row holds no verified domains. The SSO test tenant for this release is
  **`ssotest2`** with the same two verified domains; the close-out purge certifies `ssotest2`.
  Backlog: reusable slugs after termination, the tenant UUID staying the permanent identifier.
- **3.2 Entra refusal setup (owner decision, Oct 23, 2026):** the trial tenant has only its own
  domain, which `ssotest2` verifies (Phase 1b could not test this case). Narrowing the domains
  for the test was not possible: verified domains are fixed at tenant creation (backlog). The
  refusal is tested with an Entra **guest user** whose address is outside both domains.

### Issues found and fixed during the release

| # | Where | Issue | Fix |
| --- | --- | --- | --- |
| F1 | 1.2, P1c-10 | The deploy script's step 10 polled `/api/v1/healthz`, which requires a signed-in user and answers 401 to `curl`, so every deploy would have failed at its checks. Found after the runbook was written and before the deploy. | PR #61 (2244b09): the script checks the public `/healthz`, on loopback and over TLS; `test_deploy` pins the path. In the release commit. |
