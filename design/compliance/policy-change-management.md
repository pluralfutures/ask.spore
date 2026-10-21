# Change Management Policy — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Owner legal entity name], [security lead name], [date] |
| To finalise, the owner must | (1) turn on branch protection on `main` (P1b-13c) and record the date; (2) decide who reviews pull requests while there is one internal person (see §3); (3) approve and sign. |

---

## 1. Purpose and scope

How changes reach production: application code, database schema, prompts, model and provider configuration, infrastructure (Compose, Caddy, Authentik, RAGFlow versions) and corpus content.

## 2. Rules

1. **Every code change goes through a pull request to `main`** with the CI, Eval and Guardrails workflows green. A red check is not merged.
2. **Schema changes only by Alembic migration.** A new tenant table carries `tenant_id`, RLS and a tenant-first index in the migration that creates it.
3. **Prompts are versioned files** under `config/prompts/`; a change is a new version file plus an eval run against the last baseline.
4. **Model and provider changes** are edits to `config/models.toml`, checked at start-up against the allow-list. No `-latest` aliases. A new external host or model needs the gate in `paperwork-checklist.md` first.
5. **Isolation controls carry negative tests** (cross-tenant read returns nothing, prompt has no identifiers, log line has no body).
6. **Deploys** run from `main` on the Instance by the operator, following a runbook; the deployed commit is recorded in the findings file of the phase.
7. **Corpus changes** go through the source register. From Phase 1b (P1b-01) nothing reaches RAGFlow before a reviewer approves.
8. **Emergency changes** may be deployed first and reviewed within 2 working days; the reason is written in the pull request.
9. **Pinned versions.** RAGFlow and Authentik image tags are pinned; pinning by digest from Phase 1b (P1b-15).

## 3. Roles

The owner is the only internal person and approves changes. Pull requests are reviewed by an independent Claude review session for releases (findings §12); a second human reviewer does not exist yet (`risk-register.md` R-25).

## 4. Controls and evidence

| Control | Evidence the system already produces | Status |
| --- | --- | --- |
| PR history (CC8.1) | GitHub pull requests and merge commits on `main` | Built |
| CI gates (CC8.1) | Workflows `CI` (ruff, `mypy --strict`, pytest, web lint, typecheck, tests), `Eval`, `Guardrails` | Built |
| Required checks before merge (CC8.1) | — ; six PRs were merged red in the Phase 1a release (findings §10, F9) | From Phase 1b (P1b-13c) |
| Schema test at head (CC8.1) | `test_schema::test_tenant_tables_list_is_complete` | Built |
| Prompt versioning and eval (CC8.1) | `[prompts]` in `config/models.toml` (`corpus_only = "v5"`, `general_knowledge = "v2"`); eval runs recorded as metrics only (findings §11, G6–G9) | Built |
| Eval gate in CI against baseline | — | From Phase 1b (P1b-15) |
| Independent release review (CC8.1) | Findings §12, signed review at f7b76b3 and follow-up e0435c1 | Built (per release) |
| Configuration audit (CC8.1) | `operator.entitlements_changed`, `operator.workspace_tags_changed`, `operator.source_downloadable_changed`, `ingest.source_retagged` with before and after | Built |
| Images pinned by digest | — | From Phase 1b (P1b-15) |
| Blueprint for Authentik configuration | — | From Phase 1b (P1b-08) |

## 5. Review and approval

Reviewed once a year. Next review: [date].

Approved by: [security lead name], for [Owner legal entity name], date [date].
