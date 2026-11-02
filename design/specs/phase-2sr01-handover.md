# Phase 2SR01 — handover to the build session

Oct 31, 2026. Written by the spec session for the session that builds Phase 2SR01. Paste the
"Opening prompt" below into the new session; the rest of this file is what that prompt points
at. The build session should read this file first, then the spec, then the code it names.

## Opening prompt

> You are building Phase 2SR01 of ask.spore, "Uploaded crawls", from
> `design/specs/phase-2sr01-build-spec.md`, which the owner approved on Oct 31, 2026. Start by
> reading `design/specs/phase-2sr01-handover.md`, then the spec, then `CLAUDE.md`. Work on a new
> branch `claude/p2sr01-uploaded-crawls` off `origin/main`. Build the items in the spec's order,
> P2SR01-01 to P2SR01-07, one commit per item with the item ID in the message, each with its
> tests, `ruff`, `mypy --strict` and the suite green before the next item. Do not build anything
> on the spec's "Not in this phase" list; put ideas in `design/specs/backlog.md`. Record every
> place the build departs from the spec, and every question for the owner, in
> `design/specs/phase-2sr01-findings.md` §1, as the Phase 2A findings file does. Do not open a
> pull request unless asked. P2SR01-08 (release on the Instance) is a separate session.

## What this phase is, in one paragraph

The content team uploads a ZIP of Markdown files, one crawl of one domain made with
[markdown.new](https://markdown.new/), together with the site's name, start URL and crawl
date. An editor uploads and a reviewer releases; the worker imports each file as a page of a
`sites` row with `origin = 'upload'`, so it behaves exactly like a page the platform crawled
itself: same register row, same `site_pages` row, same withdrawal, takedown, pause,
supersession-by-URL and reinstatement, same roll-up in the tenant file list. Nothing changes
for the chat path or for tenants.

## Decisions already taken (do not reopen)

All in the spec's "Decisions" table and "Owner decisions of Oct 31, 2026". In short:

| Decision | Consequence for the build |
| --- | --- |
| D1 front matter, from real markdown.new files | URL from the leading `<!-- Source: <url> -->` comment; `url:` key accepted as an alternative and must agree. `title` from the block; `date` optional; nested `meta` mapping skipped. No pre-processing of the owner's files. |
| D2 site with pages, `origin = 'upload'` | Reuse `sitecrawl._Crawl` for page admission; do not copy it. |
| D3 declaration only, no robots/TDM network check | `allow_decision = 'declared'`; `declared_robots_honoured` constrained true; the policy documents are updated in P2SR01-07 to say so. The start-URL public-address check in `register_site` stays (it is the SSRF guard). |
| D4 content console + CLI; editor uploads, reviewer releases | Routes under `/api/v1/content/sites/…/uploads`; CLI `ask-spore sites upload-crawl`. |
| D5 full or partial per upload, default partial | `full` runs the sweep that withdraws absent pages (`not_in_upload`); `partial` touches nothing absent. |
| D6 limits 200 MB / 2,000 members / 5 MB each / 500 MB uncompressed | Enforced on the uncompressed stream, member by member; never extract to a directory. |
| D7 every upload released by a reviewer | Even on an already approved site. |
| D8 no HTML snapshot | `snapshot_path` null; the staged Markdown is the provenance copy. |
| D9 `fetched_at` = crawl date (midnight UTC) | On every page of the upload. |
| D10 one pending upload per site | Second upload while one is `staged` or `queued` is refused. |
| D11 (proposed, treat as taken unless the owner objects) | Uploaded text ingested as supplied, boilerplate included; no trafilatura pass. |
| Declaration sentence | Fixed text in the spec's owner-decisions table, row 2; the CLI flag prints it and refuses to run without it. |
| Priority | Immediate; branch from `main` now. The Phase 2A code it relies on (revision 0070, P2A-03 inherited pause, P2A-12 a reinstatement) is already on `main`. |

## Where the existing code is

Read these before designing anything; the spec was written against them.

- `apps/api/app/content/models.py`: `Source`, `Site`, `SitePage`, the status tuples and
  check constraints. New: `sites.origin`, `ALLOW_DECISIONS += 'declared'`, table
  `site_uploads` (operator-owned like `sites`, outside tenant RLS; it holds no tenant data).
- `apps/api/app/content/sitecrawl.py`: the `crawl_site` job. `_Crawl.apply` / `_page` /
  `_admit` / `sweep` and `_finish` are what the import must reuse. `_admit` builds the
  register row (type `markdown`, title cut to 500, `canonical_url`, `site_id`, `snapshot_path`,
  `fetched_at`) and audits `source.proposed` + `source.approved` with `method = "site_crawl"`;
  the import uses `method = "crawl_upload"`. `WITHDRAWAL_REASONS` needs a `not_in_upload` entry.
- `apps/api/app/content/crawler.py`: `Visit` (build one of kind `page` per member, no `raw`),
  `normalise` (URL normalisation), `_same_site` (host rule), `render` (NOT used on uploads, D11).
- `apps/api/app/content/special.py`: `special_category(url, title)` and `whitelisted`.
- `apps/api/app/content/sites.py`: `register_site`, `approve_site`, `request_crawl`,
  `update_site`, `schedule_due_crawls` (the last three must refuse an upload site).
- `apps/api/app/content/store.py`: `stage` (by hash); add the `uploads/<sha256>.zip` staging.
- `apps/api/app/content/jobs.py`: `JOB_TYPES`; add `import_crawl`. Payload: `upload_id` only.
- `apps/api/app/content/worker.py`: where job types are dispatched.
- `apps/api/app/content/submit.py`: `submit_site` / `settle_site`, the CLI's pattern.
- `apps/api/app/api/content.py` and `content_schemas.py`: the console routes; `_read_upload`
  is the chunked body reader with a cap; the `/sites` routes and `SiteCreateIn` are the model
  for the new upload routes. `require_content_user`, editor vs reviewer checks are there.
- `apps/api/app/cli.py`: `argparse`; `_sites`, `_crawl_site`, `_actor_flags` (`--approve-as`),
  `_wait_flag`.
- `apps/api/app/audit/events.py`: `EXPORTED_EVENTS` / `OPERATOR_ONLY_EVENTS`; every new event
  name must be classified or the catalogue test fails. New names are operator-only.
- `apps/api/tests/test_logging_policy.py`, `test_no_bodies_in_errors.py`: the static scans;
  add the new modules. `ragflow_fake.py` and `fakes.py` for the worker tests.
- `apps/web/src/pages/content/Sites.tsx`, `SiteDetail.tsx`, `apps/web/src/lib/content.ts`,
  `apps/web/src/api/schema.d.ts` (regenerated from the OpenAPI schema; check how the repo
  regenerates it before editing by hand).
- Migrations: `apps/api/alembic/versions/`, latest `0070_source_pause.py`. One new revision.

## Gotchas found while writing the spec

- **The real files differ from Cloudflare's docs.** The URL is in an HTML comment on line 1,
  not in the block; the block has a nested `meta:` mapping; there is no date. The parser must
  skip indented blocks, not refuse them. Five real files were inspected; the spec's "The ZIP"
  section shows the shape. Build the fixture ZIPs in that shape, synthetic content only
  (`packages/eval/fixtures/uploads/`); never commit the owner's real files.
- **"Page deleted" placeholders.** Two of the five real files were deleted-page placeholders
  that differ by one line, so the duplicate-content check cannot catch them. This is a reviewer
  matter, not code; the upload report must make per-member review easy.
- **Body hashing.** Hash and stage the body after stripping the `Source` comment and the
  block, so a front-matter-only change is `unchanged` and the hash equals what the live
  crawler would store for the same text.
- **No names in logs or audit.** Member names, URLs and titles appear only in the API response
  of the upload (the inspection report) and on the console page at that moment. Audit metadata
  and log lines carry IDs, codes and counts. The 422 body for a whole-upload refusal carries
  the code and the member *index*, not its name.
- **ZIP safety.** Refuse absolute names, `..`, symlinks, nested archives, encrypted members
  (`unsafe_member`). Enforce the per-member cap while streaming the uncompressed bytes; a ZIP
  can declare a false uncompressed size. Skip directories, hidden entries, `__MACOSX/`,
  non-Markdown members as `skipped_not_markdown`.
- **Inherited pause (P2A-03).** A changed version of a paused page must come in paused; reuse
  the existing path (`_inherit_pause` in `ingest.py`), it is keyed on `supersedes_id`.
- **Sweep and takedowns.** `sweep` already respects `_held` (a takedown or a pending
  withdrawal on the current row) and pending supersessions; `full` mode must go through it,
  not around it.
- **Upload sites and the scheduler.** `schedule_due_crawls` selects by `status, next_crawl_at`;
  an upload site must never get a `next_crawl_at`. `_finish` sets it from `site.schedule`,
  which is `none` for upload sites, so it stays null, but add the test.
- **Design documents move with the code** (CLAUDE.md). P2SR01-07 is part of the same PR:
  architecture §6.2 and §6.4, `policy-content-sourcing.md` §4.2 and its evidence table,
  `risk-register.md`, `records-of-processing.md`. The D3 divergence from the compliance guide's
  crawler rule must be stated, not hidden.

## Order of work and definition of done

1. P2SR01-01 migration and model changes, with the migration test.
2. P2SR01-02 `app.content.uploads.inspect_zip` and the two upload routes, with the fixture ZIPs.
3. P2SR01-03 release/reject routes and the `import_crawl` job.
4. P2SR01-04 second-upload semantics (`full` / `partial`).
5. P2SR01-05 console pages, CLI command, tenant-facing tests, Playwright.
6. P2SR01-06 audit catalogue and logging scans.
7. P2SR01-07 documents.

Done means: `uv run --directory apps/api ruff check . && uv run --directory apps/api mypy app`,
`uv run --directory apps/api pytest`, `pnpm --dir apps/web lint && pnpm --dir apps/web typecheck
&& pnpm --dir apps/web test` all green; every item's tests present including the negative
cases the spec lists; `phase-2sr01-findings.md` written; branch pushed. P2SR01-08 (the
Instance release, drill with a synthetic ZIP, findings §5, short independent review) is the
next session's work.

## Questions to put to the owner only if they block

- Whether D11 stands (ingest as supplied). Assume yes.
- Anything in the five real files that the fixture shape does not cover once more files are
  seen (for example a page with no title meta tag and therefore no block at all; the spec says
  accept it with the title from the first heading).
