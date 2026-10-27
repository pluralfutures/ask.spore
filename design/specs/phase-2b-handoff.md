# Phase 2B: handoff to the Instance session

Oct 27, 2026 · For the Claude Code session running on the Instance. Branch
`claude/pensive-cori-mgqfmt`. Read `CLAUDE.md`, `design/specs/phase-2b-build-spec.md` ("Build
notes", "Owner decisions" 6 and 7) and `design/specs/phase-2b-findings.md` first.

## Why this exists

The build session had no Docker and no RAGFlow, so one change is untested and has to be
checked here before it is deployed. Nothing below is deployed yet.

## Rules

- Do not deploy this branch to the running app, and do not run migration 0071 against the live
  database, until the owner says release. Use a throwaway database or a scratch Compose project
  (its own name, its own volumes) for every check.
- Internal tenant and synthetic fixtures only (`packages/eval/fixtures/`). Never client
  documents or real queries. Delete any temporary tag, dataset or container afterwards.
- If a check fails, do not remove `internal: true` from the `ragflow` network to make it pass.
  Report what failed and what it needs; the owner decides.
- Do not open a PR. Push to the same branch. Record results in `phase-2b-findings.md`.

## Check 1: RAGFlow has no route out (owner decision 7)

`infra/ragflow/docker-compose.yml` now makes the `ragflow` network `internal: true`. The web UI
moved to a `ragflow-ui` Caddy proxy on a second network. Applying it recreates the network and
restarts the RAGFlow tier. In a scratch project, confirm:

1. From inside the `ragflow` container an outbound request fails: `curl -m 5 https://example.org`.
2. The API and worker still reach `http://ragflow:9380`: a PDF, a DOCX, a `.md` and a `.txt`
   upload each parse to completion through the API.
3. A restart of the tier comes up healthy and its logs show no download attempt (DeepDoc models,
   the embedding model, NLTK data). If something downloads at start-up, say what and where it is
   cached; the fix is to put it on a volume first.
4. The SSH tunnel to `127.0.0.1:${RAGFLOW_UI_PORT}` opens the UI and a document page, including
   its `/api/` calls.
5. A crawled page with an image in its HTML (a synthetic local site, as the crawler tests use)
   ingests, and the stored Markdown holds no image reference.

## Check 2: what applying it means for the live Instance

Write down, without doing it: the exact commands to apply it (`infra/scripts/deploy.sh` or
`docker compose up -d`), how long the tier is down, whether anything in `infra/README.md` or the
runbooks names the old UI publishing, and the rollback (restore the previous compose file, bring
the tier up again).

## Check 3: the full suites on the Instance's stack

Run the API suite against a throwaway PostgreSQL (`REQUIRE_DB_TESTS=1`), `ruff`, `mypy --strict`,
and the web `lint`, `typecheck`, `test`. Report any failure that is not in
`tests/test_workspace_summary.py` or the files this branch changed.

## Report back

Pass or fail for each check above, with the command and the one line of output that shows it.
Anything that needs an owner decision goes at the top.
