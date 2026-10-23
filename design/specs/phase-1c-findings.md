# Phase 1c Findings

Oct 23, 2026. Build record of Phase 1c (`phase-1c-build-spec.md`). Each build session writes
its own section; the integration and the release add theirs.

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
