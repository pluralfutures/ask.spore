# Phase 2A release runbook (P2A-14)

Brief for the session that releases Phase 2A on the Instance. Written Oct 25, 2026 by the
orchestrating session after the integration (`phase-2a-findings.md` §4). Read `CLAUDE.md`,
`phase-2a-build-spec.md` (the decisions table and decisions 18 to 29), `phase-2a-findings.md`
(all sections; §3.5 and the "Notes for the integration" of §2 name the moving parts), the
Phase 1c release record (`phase-1c-findings.md` §5) and `infra/README.md` first. This runbook
adds nothing to the spec; it orders the release work and fixes the values.

## Ground rules

As in the Phase 1c runbook: run on the Instance from `/root/ask.spore` on `main`, branch work
in a separate `git worktree`; changes on branch `phase-2a/release`, pushed for the owner to
merge, then pulled; never push to `main`, never open a PR. Metadata-only output. No wildcard
or recursive deletes. Owner decisions arrive in this brief or in a later message quoting the
owner; anything else that needs one: stop that item, report, continue with the rest.
CLAUDE.md non-negotiables are release blockers; every fix is an F-row in findings §5.

## Fixed values

| Item | Value |
| --- | --- |
| Public host | `askspore.myceliumgastronomy.com` |
| Release commit | `main` after the Phase 2A pull request merges (the session records the hash) |
| Deploy | `infra/scripts/deploy.sh --public-url https://askspore.myceliumgastronomy.com`; never by hand |
| Migrations | 0070 (pause) then 0065 (support grants), chained in that order |
| Trust page flag | `ASKSPORE_TRUST_PAGE=unpublished` in `infra/.env` (the default); the route answers 404 |
| Security contact | `security@myceliumgastronomy.com` (decision 27) in `security.txt` and on the disclosure page; the mailbox must exist and be read before the files go live |
| Holiday calendar | `config/holidays.toml`, `active = "france"` (decision 29) |
| Eval baseline | unchanged from Phase 1c (no prompt changed); the run proves retrieval still works with the toggle in place |
| Pause drill target | one `sample-reports` source of the internal tenant; never a client dataset. Every `sample-reports` source is also in a client dataset (probe §"Scope"), so the drill pauses it for that client too for its duration: run the drill when the client has no active users, and resume within the same sitting |

## Owner inputs needed before the session starts

1. The `security@` mailbox exists and is read (fixed values).
2. A keyboard block of about thirty minutes: a support grant opened from the tenant admin
   page of the internal tenant and read from the operator console; the pause drill watched
   from the content console and a chat window.
3. Whether the restore test and the nightly backup (the Phase 1c follow-up, still open) have
   been done; the release records their state but does not depend on them.

## Order of work

### 1. Visual baselines (first, before the PR merges)

In the pinned image (`apps/web/e2e/visual/run-in-image.sh`, as Group A did on the Instance):
run the visual suite on the integration branch, read every diff image, confirm each change
is one Phase 2A made (admin page: Usage section, consent column, export dates; operator
tenant page: Support access tab; operator workspaces: the "Sources in its tags" link,
already refreshed), then update those baselines only. Commit to the integration branch
(the owner merges), so CI's `web-visual` job is green on the PR.

### 2. Deploy by script

Pull `main`, deploy, check `/healthz`, the two migrations applied (`alembic current`), the
worker's startup lines, the dataset counts. Fetch `/.well-known/security.txt` and
`/security-disclosure` without a session: 200, the contact address, no consent redirect.
Fetch `/trust`: 404.

### 3. Isolation tests and the independent review

Full suite with the database on the Instance (throwaway PostgreSQL container, never the live
cluster). An independent review session on `main` at the release commit, as Phase 1c §5.2:
every CLAUDE.md non-negotiable, with the Phase 2A specifics named: no dataset or document ID
from a request on the pause routes; the toggle's log fields; `support_grants` RLS and index;
no conversation text in any log line of the support view; the export allow-list.

### 4. Pause drill (P2A-14)

On the internal tenant, in one sitting: ask a question that cites the target source and note
the citation; pause the source from the content console with a reason; ask again: no citation
of it, no cache hit (a new answer); the file gone from the workspace library, its download
refused; the earlier conversation shows the citation labelled "currently unavailable" with
its excerpt; resume; ask again: cited; the label gone; `datasets sync` reports no mismatch.
Each step's audit event present (`source.paused`, `source.resumed`, `download.refused` with
`paused`). Record timings (the toggle took about 1 s per large document in the probe).

### 5. Support access drill (P2A-08)

Internal tenant admin grants settings access for 15 minutes with a note; the operator reads
the settings through the console; the admin page shows the view; the admin revokes; the next
operator read is refused (404); a grant on one of the admin's conversations, read once, then
left to expire; the purge job closes it (`support.grant_expired`). Nothing of the conversation
in the api or worker logs (grep the key names only).

### 6. Evals

Eval set v1 and the guardrail eval against the Phase 1c baseline, no regression expected.
Outputs under `/srv/ask-spore/eval-runs/`, redacted results under `packages/eval/results/`.

### 7. Close-out

Findings §5: release status, the review signed, the drill tables, F-rows, the eval table,
the exact `main` commit the Instance runs. Open items left to the owner: the trust page's
final text and flag; the legal entity on the disclosure page; the first quarterly access
review date (H2); the restore test and backup if still open; `bugs-to-investigate.md` B-1.
Backlog: every deferral as a dated line. Spec status line: "Phase 2A closed" with the date,
once the owner confirms.

## Not in this release

Audit disposal (backlog, "Enterprise requirements"); a tenant-side pause or upload; source
filters; client-supplied documents; web search; passkeys; monitoring; the status page itself
(D6 names its source only); anything in Phase 2 beyond this spec.
