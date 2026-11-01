# Phase 2SR01 Findings

Oct 31 to Nov 1, 2026. Build record of Phase 2SR01, "Uploaded crawls"
(`phase-2sr01-build-spec.md`, approved Oct 31, 2026), kept like `phase-2a-findings.md`:
where the build differs from the spec, and why, and the questions for the owner.
Metadata only: no member name, page URL of a real site, title, page text, token or key is
recorded here. Every ZIP named below is a synthetic fixture under
`packages/eval/fixtures/uploads/`.

## 1. Build (P2SR01-01 to P2SR01-07)

Branch `claude/p2sr01-uploaded-crawls`, from `origin/main` at 09d659f, built in the
worktree `/root/ask.spore-p2sr01` (the live tree stays on `main`). One commit per item:
7cdc6b3 (P2SR01-01), fbc1c38 (P2SR01-02), 9c040ec (P2SR01-03), b8df0e3 (P2SR01-04),
743d58d (P2SR01-05), a1f231d (P2SR01-06), 8564445 (a P2SR01-03 follow-up, below), and the
P2SR01-07 commit that adds this file. One migration, **0080** (`0080_uploaded_crawls`).
Built and tested on the Instance's host against a throwaway PostgreSQL 16.15 container
(tmpfs, loopback port 55433) and the RAGFlow fake; the live services were not touched.

### P2SR01-01 Register: upload sites

| Spec says | Built |
| --- | --- |
| One migration | **0080 revises 0065**, not 0070: `main`'s head is 0065 (the Phase 2A integration re-parented 0065 onto 0070) |
| `sites.origin` in `('crawl', 'upload')`, default `crawl`, never changed after creation | As specified; "never changed" is enforced by a trigger (`sites_origin_fixed`, `check_violation`), since a check constraint cannot see the old value |
| An `upload` site has `schedule = 'none'` and `next_crawl_at IS NULL` | Check `upload_unscheduled` |
| `ALLOW_DECISIONS` gains `declared` | As specified |
| `site_uploads` columns | As listed, plus **`accepted_count`, `refused_count`, `skipped_count`** (the inspection's counts, so the console can show them without the report), **`imported_at`** and **`updated_at`**. `uploaded_by` is nullable (the CLI run as the operator's shell has no editor, as `sites.proposed_by` is nullable). `staged_path` is nullable and cleared when the ZIP is deleted. Counts default 0 and are constrained non-negative. Further checks: `release_recorded` (queued, imported and failed have `released_by` and `released_at`), `rejection_noted`, `error_when_failed` (a code, only when failed) |
| `crawled_on` not in the future | The database checks it against the upload's own date (`crawled_on <= uploaded_at` in UTC), which is deterministic; the API refuses a date after today (UTC) before reading the body (`crawled_in_future`) |
| One pending upload per site (D10) | In the code (`upload_pending`) **and** in the database: a partial unique index on `site_id` where `status IN ('staged', 'queued')` |
| Job type `import_crawl`, payload `{"upload_id": …}` only | As specified; `upload_id` is also part of the one-active-job-per-subject index (otherwise two imports would collide on the index's NULLs), and a check `import_names_upload` requires the key for that type |
| `request_crawl`, `schedule_due_crawls` and the settings route refuse an upload site; `update_site` refuses a schedule other than `none` | As specified (`origin_upload`). **Not in the spec:** `approve_site` refuses an upload site too (approval comes with the release of its first upload, P2SR01-03), and the `crawl_site` job itself refuses one (a crawl job queued by hand fetches nothing) |
| Audit | `site.proposed` carries `origin` in its `after`. The audit writer's allow-lists gained the metadata keys `upload_id`, `members`, `accepted`, `refused`, `skipped`, `new`, `changed`, `unchanged`, `blocked`, `withdrawn` and the change field `origin`; the log allow-list gained `upload_id` |
| Downgrade | Drops `site_uploads` and the `import_crawl` jobs; upload sites stay as `crawl` sites with no schedule; a `declared` decision becomes `unchecked` |

### P2SR01-02 Upload: validation and staging

| Spec says | Built |
| --- | --- |
| `inspect_zip(path \| bytes) -> UploadReport` | `inspect_zip(source, *, host, special=None, scope=None)`: the host is needed for the same-host rule. With the site's special-category whitelist and scope rules it **notes** the accepted members the import will block (`special_category` with the category, `out_of_scope`), so the editor sees them before release. `pages(source, host=…)` yields the accepted pages one at a time for the import |
| Codes | Whole upload (422 with code and member index): `unsafe_member`, `duplicate_url`, `too_many_members`, `no_pages`, and also `not_a_zip` and `total_too_large`. Per member: `url_missing`, `url_mismatch`, `bad_date`, `front_matter_invalid`, `empty`, plus **`bad_url`** (not an absolute http(s) URL, or over 2,000 characters), **`off_site`** (another host), **`not_utf8`** (also a NUL character) and **`member_too_large`**. A ZIP over 200 MB is 413 `too_large` |
| Limits (D6) | As specified, counted on the uncompressed stream. **Added:** at most 20,000 entries of any kind in the ZIP's central directory (`too_many_members`), a bound on what the directory alone makes us hold in memory |
| A ZIP can declare a false uncompressed size | Python's `zipfile` stops at the declared size and fails its own length and CRC check, so such a member refuses the **whole** upload as `not_a_zip` (with its index), rather than being listed as `member_too_large`. Tested with a forged central directory |
| Nested archives | Refused by suffix (`.zip`, `.gz`, `.7z`, `.rar`, `.tar` …) and by content: a `.md` member whose bytes start with an archive's magic number is `unsafe_member` too |
| Front matter: keys in lower case, plain or quoted scalars, indented blocks skipped | A key in upper case is `front_matter_invalid`. A literal or folded block (`key: |`) and a YAML list under an ignored key are skipped like an indented mapping; under `title`, `date` or `url` they are `front_matter_invalid`. Double-quoted values take JSON-style escapes (`\"`, `\\`, `\uXXXX`). Titles have control characters removed and whitespace collapsed before the 500-character cut |
| The 422 body: the code and the member index | `{"detail": {"code": …, "member": index or null}}`; every other refusal keeps the console's plain `{"detail": code}`. A new upload site at a start URL already registered is 409 `site_exists` (never merged) |
| A request naming dataset or document IDs | The routes are multipart forms, which cannot refuse unknown fields as the JSON bodies do (`extra="forbid"`); unknown fields are ignored and never read. Tested |
| Fixtures under `packages/eval/fixtures/uploads/` | 23 ZIPs built by `make_uploads.py` (host `www.example.org`, a reserved name that resolves publicly, so the P2SR01-08 drill can register it). The test compares the committed ZIPs with the script's output by member names and contents, not bytes (zlib versions differ) |
| A new site through an upload | Registered `proposed`, `origin = 'upload'`, schedule `none`, in the same transaction as the upload row. Its `max_pages` keeps the default 50, which means nothing for an upload site; the console hides it |

### P2SR01-03 Release and the import job

| Spec says | Built |
| --- | --- |
| A reviewer releases or rejects; the report is in front of the reviewer (D7); the report with names is never stored | **Not in the spec's routes:** `GET /api/v1/content/sites/{id}/uploads/{upload_id}/report` reads the staged ZIP again and returns the same report, for the reviewer's release (any content role may read it; only while `staged`). Nothing is stored; the names exist in the ZIP the editor uploaded. Question 1 |
| Release on a `proposed` site approves it | Through `sites.approve_locked` (the same update and `site.approved` audit as `approve_site`), in the release's transaction. `site.upload_released` carries `status: site_approved` or `site_already_approved` and `self_approval` |
| Reject with a note | The staged ZIP is deleted at once. **The site is left as it is**: a proposed site whose first upload is rejected stays proposed and takes a next upload. Question 2 |
| Built from `sitecrawl._Crawl`, not copied | `_Crawl` gained four settings with the live crawl's values as defaults: `method` (`site_crawl` / `crawl_upload`), `proposer` and `approver` (the site's / the uploader and the releasing reviewer), `fetched_at` (now / the crawl date at midnight UTC), and a snapshot only when the visit has raw HTML (D8). The live crawl's behaviour is unchanged (its tests pass unmodified) |
| Rows in the releasing reviewer's name | `approved_by` = the releaser, `proposed_by` = the uploader; the audit events of the job carry no actor (`actor_user_id` null, `method: crawl_upload`), as the crawl job's do |
| (not in the spec) | The job checks that the releaser **still holds** `content_reviewer` (`releaser_lacks_role`), as a crawl checks its approver |
| A failed job leaves the site untouched | The ZIP is re-hashed and re-inspected before any page is touched (`upload_missing`, `upload_altered`, or the inspection's code). **Follow-up 8564445:** an unexpected error during the import now fails the upload (`internal_error`) instead of leaving it `queued`, which would have blocked the site's next upload; pages admitted before such an error stay, as after an interrupted crawl. Imports are not retried by the worker |
| The staged ZIP is deleted | After the import or the rejection; kept if another pending upload (of another site) staged the same bytes, since the file is named by its hash |
| `_finish` as today | Called with no allow decision, so the release's `allow_checked_at` stands; `last_crawl_status = 'imported'` |
| A page the reviewer withdrew stays blocked | As the crawler does: such a member is skipped without a count, so it is not in `blocked_count` |

### P2SR01-04 Second upload

| Spec says | Built |
| --- | --- |
| Full and partial | The code is in the P2SR01-03 commit (one import function); the P2SR01-04 commit is its tests. `full` passes every live page absent from the ZIP to the crawler's own `apply` as a `missing` visit (`not_in_upload`), then the crawler's sweep withdraws, holding back what a pending supersession needs and honouring `_held` as for a crawl. A removed page keeps its last fetch date |
| The count before release | Computed at staging (returned to the editor) and again each time the reviewer's report is read; shown on the release button ("Release (withdraws N)"). The release does not re-check that the number is unchanged; backlog |
| An unchanged member | Not re-parsed; its page's fetch date moves to the new crawl date (D9) |

### P2SR01-05 Console, CLI and the tenant-facing path

| Spec says | Built |
| --- | --- |
| Console | As specified: "Upload crawl" on the Sites page and on an upload site's page, the declaration checkbox with the owner's sentence (with `<host>` and `<crawled_on>` until known), the report kept in the page's state only, an `uploaded` badge and the crawl date (`SiteOut.last_crawled_on`, the crawl date of the last imported upload), the uploads list, and Release and Reject for a reviewer with the report read again. On an upload site "Crawl now", "Approve and crawl", the schedule and the page budget are hidden; scope rules and the special-category whitelist stay editable (they apply at the next import). New copy: question 4 |
| CLI prints the report with member names to the terminal, codes and counts to the log | Standard output is the JSON log stream and `print` is banned in `app/` by the logging policy, so the report goes to the **controlling terminal** (`/dev/tty`) only. Without a terminal (a non-interactive run) it is not shown anywhere, and the log line says `report_not_shown_no_terminal`. Question 5 |
| `--declare-robots-honoured` prints the sentence and refuses to run without it | Without it the run exits with the sentence (site host and crawl date filled in); with it the sentence is written to the terminal |
| CLI uploader | The operator's shell (no editor, as for `ingest-manifest`), or with `--approve-as` that reviewer, who must then also hold `content_editor` (self-approval, audited, as `ingest` and `crawl` do). No `--propose-as` (not in the spec; backlog). `--wait` waits for the import, then the page ingestions |
| Tenant-facing tests | No code: an uploaded site rolls up in the file list of a tenant whose workspace holds the tag, is absent for one that does not, its pages are never downloadable, and their provenance carries the page URL, title and publisher (and is wrapped untrusted, type `markdown`) |
| Playwright | `e2e/uploads.spec.ts`. The visual baselines `19-content-sites` (desktop, phone) were regenerated in the pinned image: the diff is the new form only |

### P2SR01-06 Logging and audit catalogue

The five events were classified operator-only with P2SR01-02 (the catalogue test fails on
an unrecorded or unclassified name). The static scan is module-specific, like the support
view's: in `app.content.uploads` and `app.content.uploadcrawl` every `log()` takes only
`upload_id`, `site_id`, `status`, `count`, `error_code`; every `record()` a literal mapping
of allow-listed keys (`_audit`'s callers held to the same keys); every raise a constant, a
code or a member index; nothing reads a `name`, `url`, `title` or text attribute into any of
them. Two refusals built with string concatenation were made literal for it. The runtime
capture uploads, releases and imports a ZIP with an odd member name and title and finds
neither in stdout, stderr, log records, audit rows, jobs or `site_uploads`; the register row
holds the title, as for a crawled page. `test_no_bodies_in_errors` gained the 422 case.

### P2SR01-07 Documents

Architecture §6.2 (row "Uploaded crawl") and §6.4 (the declaration paragraph, naming the
departure from the compliance guide's crawling rule), `policy-content-sourcing.md` §4.2 and
§7, `risk-register.md` (**R-38**, a declaration made in error), `records-of-processing.md`
(C1 note). The compliance guide itself is not edited: question 3. `backlog.md` gained the
ideas raised during the build.

### Checks run

On the branch head before this section, on the Instance's host (throwaway database, fakes):

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | `All checks passed!` |
| `uv run --directory apps/api ruff format --check .` | `236 files already formatted` |
| `uv run --directory apps/api mypy app` (strict) | `Success: no issues found in 116 source files` |
| `uv run --directory apps/api pytest` (database, `REQUIRE_DB_TESTS=1`) | `1789 passed, 2 skipped, 1 deselected` (1716 before P2SR01-02) |
| `pnpm --dir apps/web lint`, `typecheck`, `test` | Prettier clean, `tsc -b` clean, `Tests 214 passed (214)` |
| `pnpm exec playwright test` (pinned image, bridge network) | `603 passed` |
| `playwright test --config playwright.visual.config.ts` (pinned image) | 132 passed, 2 failed before the `19-content-sites` update; 2 passed after it |

`apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` are regenerated. No dependency
changed, no Compose change, no prompt, model, retrieval or chunking change, so eval set v1 was
not rerun. Not run: P2SR01-08 (the Instance release and drill).

### Questions for the owner

1. **The reviewer's report.** D7 asks for the report in front of the reviewer, and the spec
   keeps no names on the server. The build adds a read-only route that inspects the staged ZIP
   again for the reviewer (nothing stored; available while the upload waits). Keep it?
2. **Rejecting a new site's first upload** leaves the site `proposed`, ready for a corrected
   ZIP. Should the rejection reject the site too when it has no other upload?
3. **The compliance guide.** D3 departs from its "if a site has reserved rights in a
   machine-readable way, do not crawl it". The architecture, the sourcing policy and the risk
   register now say so (R-38). Should the guide carry a dated note as well, as the Oct 18
   addendum did for external models?
4. **New console copy** (the UX rule: new words need approval): "Upload crawl", "One ZIP of
   Markdown pages from one crawl of …", the partial and full radio texts, "Uploaded: it waits
   for a reviewer to release it.", "uploaded" (badge), "uploads" (schedule column), "uploaded,
   no snapshot", "pages come from uploaded crawls, never crawled by the platform", "Approve site
   and release", "Release (withdraws N)", "Releasing its upload approves the site.", the member
   outcome texts and the refusal messages in `apps/web/src/lib/content.ts`, and the allow
   decision "declared by the uploader (robots.txt, TDM and noai), released by a reviewer".
5. **The CLI report goes to the controlling terminal only**, so names never enter a captured
   log stream; a run without a terminal shows counts only. Acceptable?
6. **D11** (ingest as supplied) is built as proposed.
