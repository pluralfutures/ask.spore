# Phase 2SR01 Build Spec — Uploaded Crawls (Markdown ZIP into the library)

Oct 31, 2026 · Status: **draft for owner review**; owner decisions D1 to D6 taken Oct 31, 2026
(table below), D7 to D10 proposed · Target duration: 1–2 weeks, one build session · Special
request (SR): sits outside the normal phase cycle and does not reopen Phase 2A or start Phase 2B

Source decisions: the owner's request of Oct 31, 2026 (a platform-side upload of a ZIP of
Markdown files, one crawl of one domain converted to Markdown by an external tool, with the
website name, URL and crawl date sent along); architecture §6.1, §6.2 ("Crawled website"),
§6.4 and §15.3 (Markdown accepted, "naive" method); the compliance guide ("Content licensing
and crawling"); `policy-content-sourcing.md` §4.2; Phase 1b P1b-04 (sites and pages) and
Phase 2A P2A-03 (inherited pause) and P2A-12 (a) (reinstatement).

## Goal

Let the content team bring a website into the corpus from a crawl made **outside the
platform**: an external tool fetches the pages and converts them to Markdown, the editor
uploads the result as one ZIP with the site's name, start URL and crawl date, a reviewer
releases it, and the worker imports every file as a page of a registered site. The result is
indistinguishable, for tenants and for the register, from a site the platform crawled itself:
one `sites` row, one `site_pages` row and one register row per page, the page URL as the
canonical link, the same withdrawal, takedown, pause, supersession and reinstatement paths,
and the same roll-up to the site in the workspace file list. Nothing changes for the chat
path: the prompt carries the same provenance (publisher, title, date, page URL), the retrieval
call is unchanged, and no tenant sees a new surface.

Why a special request: the platform's crawler (P1b-04) cannot reach every site worth
indexing (JavaScript-rendered pages, sites that need a specialised converter), and the owner
already runs such crawls with an external tool. This spec adds the import path only; it does
not change the crawler.

Exit criteria (all must hold):

- An editor uploads a ZIP from the content console and from the CLI; a reviewer releases it;
  every accepted Markdown file is an ingested page of the site with the page URL as canonical
  link, cited and listed to tenants exactly as a crawled page is (P2SR01-02 to P2SR01-05, with
  the negative tests).
- A second ZIP for the same site supersedes changed pages by URL, adds new ones, and, when the
  uploader marked the upload as a full crawl, withdraws pages absent from it (P2SR01-04).
- A file without a page URL, outside the site's host, over the limits, not UTF-8, or matching a
  special-category pattern is refused or blocked with a code, listed to the editor, and never
  staged for RAGFlow (P2SR01-02, P2SR01-04).
- No log line, audit event or job payload carries a file name, URL, title or page text
  (P2SR01-06).
- The policy and architecture documents say how an uploaded crawl is checked (P2SR01-07), and
  the release checks of P2SR01-08 pass on the Instance.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- **A tenant-side upload** of any kind, and any dataset or document ID accepted from a request.
  This is a content-team (internal tenant) action only.
- **A manifest file inside the ZIP** (CSV or JSON listing files and URLs) and **path-derived
  URLs**. Per-page metadata comes from front matter only (D1). A converter that emits no front
  matter needs a pre-processing step outside the platform.
- **HTML, PDF, DOCX or PPTX members** in the ZIP. Only `.md` and `.markdown` files are imported;
  other members are listed as skipped. The single-file propose form (P1b-05) still takes those
  types one at a time.
- **Live checks of robots.txt or the TDM reservation at import** (D3, declaration only). The
  owner may add the check later as a separate item; the declaration record is designed so that
  a check can sit beside it.
- **Converting a site between origins**: a live-crawled site never takes an upload and an
  uploaded site is never crawled by the platform (P2SR01-01). Switching is a backlog idea.
- **Per-file crawl dates** (one crawl date per ZIP), **scheduling** of uploaded sites, and any
  automatic fetch of the site by the platform.
- **The client-supplied model** (ideas 2.3, architecture §15). An uploaded crawl is
  platform-gathered content (model 1) with the licence basis the editor states, as a live crawl
  is; nothing here depends on or advances P1b-19 step 2.
- Any change to prompts, `config/models.toml`, the retrieval call's shape, chunking methods,
  chat-history retention or the crawler.

## Deployment target

The Phase 2A Instance (single host, Compose, Caddy TLS, Authentik, RAGFlow `v0.27.2`, the
worker) running `main` after the Phase 2A release (P2A-14). No new service, no Compose change.
One migration: `sites.origin`, the `site_uploads` table, the `declared` allow decision and the
`import_crawl` job type. The API container needs the ZIP's staged copy under `[files]
content_root` and enough disk for 200 MB per upload plus its extracted pages, which the 100 GB
volume has; the storage alert of architecture §15.3 stays a backlog item.

## The ZIP

One ZIP per upload, for one site. Every member that is to be imported is a Markdown file
(`.md` or `.markdown`) in UTF-8 (a BOM is allowed) that starts with a front-matter block:

```
---
url: https://example.org/reports/2026/annual-review
title: Annual review 2026
date: 2026-03-14
---
# Annual review 2026
…
```

| Key | Rule |
| --- | --- |
| `url` | **Required.** Absolute `http(s)` URL on the site's host (same rule as the live crawler's `_same_site`), normalised as the crawler normalises (`app.content.crawler.normalise`: tracking parameters stripped, fragment dropped). It is the page's canonical link and its key in `site_pages`. Two members with the same normalised URL: the whole upload is refused (`duplicate_url`). |
| `title` | Optional. Falls back to the first `#` heading of the body, then to the URL path, as the crawler falls back to the path; cut to 500 characters. |
| `date` | Optional. The page's **publication** date, `YYYY-MM-DD`, from the converter's explicit page metadata only (architecture §6.4); never the crawl date. Any other form is refused (`bad_date`). |

The block is `key: value` scalar lines between two `---` lines, keys in lower case, values
plain or in single or double quotes. It is parsed by a restricted parser of our own (no YAML
library: the file is untrusted input, and nothing else of YAML is needed). Any other
construction, a missing block, an unknown key or an empty body after the block refuses the file
(`front_matter_invalid`, `front_matter_missing`, `unknown_key`, `empty`). The body **without
the front matter** is what is staged, hashed and sent to RAGFlow, so the content hash matches
what the live crawler would store for the same text and a change to the front matter alone
does not count as a changed page.

Limits (D6): ZIP up to **200 MB**, up to **2,000** Markdown members, each up to **5 MB**
uncompressed, total uncompressed size up to **500 MB**. Members that are directories,
hidden entries (`.DS_Store`, `__MACOSX/`), or files of another extension are listed as
`skipped_not_markdown` and do not fail the upload. Members whose name is absolute, contains
`..`, or is a symbolic link, nested archives, and encrypted members refuse the whole upload
(`unsafe_member`). The ZIP is read member by member with the per-member cap enforced on the
uncompressed stream, never extracted to a directory.

## Work items

Build in this order. Every change keeps the CLAUDE.md rules and adds a test, with the negative
case for every control. Item IDs go in commit messages.

**P2SR01-01 Register: upload sites.** Migration: `sites.origin` in `('crawl', 'upload')`,
default `crawl` for every existing row, never changed after creation; a check constraint that
an `upload` site has `schedule = 'none'` and `next_crawl_at IS NULL`; `ALLOW_DECISIONS` gains
`declared` (the uploader's declaration stands in for the crawler's robots and TDM check, D3).
A new operator-owned table `site_uploads` beside `sites` (outside tenant RLS, like the
register; it holds no tenant data): `id`, `site_id`, `uploaded_by`, `uploaded_at`,
`crawled_on` (date, required, not in the future), `mode` in `('full', 'partial')` (D5),
`declared_robots_honoured` (boolean, constrained `true`: the declaration is the condition of
the upload), `zip_sha256`, `staged_path` (`uploads/<sha256>.zip` under `content_root`, by hash
as every stored file is), `member_count`, `status` in `('staged', 'queued', 'imported',
'failed', 'rejected')`, `released_by`, `released_at`, `review_note`, `error` (a code), and
counts (`new`, `changed`, `unchanged`, `blocked`, `withdrawn`) filled by the import. Job type
`import_crawl` with payload `{"upload_id": …}` only. `request_crawl`, `schedule_due_crawls`
and the settings route refuse an upload site's crawl (`origin_upload`); `update_site` refuses
a schedule other than `none` for it. `register_site` keeps its start-URL check (the host must
resolve to a public address, P1b-18: this is the SSRF guard, not a crawl, and stays).
Tests: the migration test (origin default, constraints, the `declared` value); `crawl` queued
for an upload site is refused; a schedule change on it is refused; the job catalogue test
knows `import_crawl`.

**P2SR01-02 Upload: validation and staging.** `app.content.uploads`: `inspect_zip(path | bytes)
-> UploadReport` runs the rules of "The ZIP" above and returns, per member, `accepted` with
its normalised URL, or a code; it reads nothing into RAGFlow and writes nothing. The API route
`POST /api/v1/content/sites/{site_id}/uploads` (multipart: `file`, `crawled_on`, `mode`,
`declared_robots_honoured`) and `POST /api/v1/content/sites/uploads` (the same plus the
`SiteCreateIn` fields, for a new site registered `proposed` with `origin = 'upload'` in the
same transaction) are **editor** actions: they read the body with the existing chunked reader
under the 200 MB cap, inspect the ZIP, refuse the whole upload on a whole-upload code (422 with
the code and the offending member *index*, not its name, in the body; the report with member
names is returned only on success, see below), stage the ZIP under `content_root`, insert the
`site_uploads` row (`staged`) and audit `site.upload_staged` (upload ID, site ID, counts; no
names). The response is the report: per member, its name in the ZIP (the editor's own file
name, shown once in the console and never logged) and its outcome. An upload for a live-crawl
site, a withdrawn or rejected site, or with a `crawled_on` in the future is refused. One
upload at a time per site: a second upload while one is `staged` or `queued` is refused
(`upload_pending`). Tests: every refusal code has a fixture ZIP under
`packages/eval/fixtures/uploads/` (synthetic pages; a member outside the host, a missing `url`,
a bad date, a `..` name, a nested ZIP, an oversize member, a non-UTF-8 member, a duplicate URL,
an unknown key, YAML constructs the restricted parser must refuse); the stage path is by hash
and the ZIP bytes never reach the job payload; an editor can stage and a tenant admin, a
tenant user and a reviewer-less internal user cannot.

**P2SR01-03 Release and the import job.** A **reviewer** releases or rejects an upload (D7):
`POST …/uploads/{upload_id}/release` and `…/reject` (note required on reject, as for sources).
Release on a `proposed` site approves the site in the same action (`approve_site`, audited as
today) so one click serves a first upload; on an `approved` site it only releases the upload.
Release sets `allow_decision = 'declared'` and `allow_checked_at`, records `released_by`, and
enqueues `import_crawl`. The worker's `import_crawl` (`app.content.uploadcrawl`, built from
`sitecrawl._Crawl` so the page logic is shared, not copied) reads the staged ZIP, and for each
accepted member builds a `Visit` of kind `page` (URL, title, body, `published_on`, no `raw`)
and runs the crawler's own `apply`: the special-category check on path and title with the
site's whitelist (blocked `special_category`), the takedown and duplicate-content checks
(blocked `taken_down`, `duplicate_content`), the scope rules if the site has any (blocked
`out_of_scope`), an unchanged page by hash (counted, dates updated), a changed page as an
approved register row that `supersedes` the current one, a new page as a new approved row,
each in the **releasing reviewer's** name with audit `method = "crawl_upload"`, staged and
queued for `ingest_source` as the crawler does. Register rows get `site_id`, `fetched_at =
crawled_on` (midnight UTC), `published_on` from the front matter, `snapshot_path` null (D8:
the staged Markdown is the provenance copy; there is no HTML), and inherit a pause as P2A-03
describes. A page the reviewer withdrew individually stays blocked `withdrawn`; a page with a
takedown stays blocked. Then the sweep (P2SR01-04), then `_finish` with `last_crawl_status =
'imported'` and the audit `site.crawled` as today plus `site.upload_imported` with the counts;
the upload row gets `imported` and its counts, and the staged ZIP is deleted. A job that
fails (RAGFlow unreachable is the ingest jobs' concern, not this one's; failure here is a
staged ZIP that no longer passes inspection or is missing) sets `failed` with a code and
leaves the site untouched. Tests: a two-file ZIP yields two approved rows, two queued
ingestions and two live pages with the right canonical links, titles and dates; a release by
an editor is refused; a release on a withdrawn site is refused; a special-category member is
blocked and listed with its category and whitelisting it then re-uploading admits it; a
member equal to another source's content is blocked `duplicate_content`; a member at a URL
with a takedown is blocked; a paused page's new version is ingested paused; the fake RAGFlow
receives the body without the front matter; the job payload holds the upload ID only.

**P2SR01-04 Second upload: supersession, full and partial.** A later ZIP for the same site
(same host) runs the same import. A member whose body hash equals the live page's is
`unchanged`; a different body supersedes the live row by URL (the A1 supersession path
withdraws the old version once the new one is ingested, citations labelled superseded). With
`mode = 'full'` the sweep withdraws every live page absent from the ZIP as the live crawler
withdraws a removed page: `site_pages` state `removed`, reason `not_in_upload`, mapped to a
withdrawal reason in `WITHDRAWAL_REASONS`, `withdraw_source` queued and
`source.withdrawal_requested` audited with `method = "crawl_upload"`. With `mode = 'partial'`
(the default) nothing absent is touched. A `full` upload is confirmed in the console with the
number of pages it would withdraw before the release (the count comes from the inspection
report against the site's live pages; the reviewer sees it on the release button). Tests: a
changed member supersedes and the old citation shows superseded; `full` withdraws the absent
page and `partial` keeps it; an unchanged member does not re-ingest (no `start_parse` on the
fake); the confirmation count matches what the sweep then withdraws; a `full` upload never
withdraws a page under a pending takedown's due date differently from the crawler (same
`_held` rule).

**P2SR01-05 Console, CLI and the tenant-facing path.** Content console: an "Upload crawl"
action on the Sites page (new site: the site fields plus the ZIP, crawl date, full or partial,
and the declaration checkbox with its text; existing upload site: the same without the site
fields), the inspection report shown after the upload (member name and outcome, the counts,
and for `full` the pages it would withdraw), an `uploaded` badge and the crawl date on the
site list and detail, the uploads list on the site detail with status, counts, releaser and
note, and "Release" and "Reject" for a reviewer; "Request crawl" and the schedule field are
hidden for an upload site; the file-name report is never stored or shown again after the page
is left (the server keeps counts and codes only). CLI: `ask-spore sites upload-crawl <zip>
(--site <id> | --start-url … --name … --publisher … --licence-basis … --tag …) --crawled-on
YYYY-MM-DD [--full | --partial] --declare-robots-honoured [--approve-as <reviewer email>]
[--wait]`, the same code path (`--approve-as` releases, as it approves in `ingest` and
`crawl`), printing the report with member names to the terminal and codes and counts only to
the log. Tenant-facing: no new code; this item adds the tests that an uploaded site's pages
are listed rolled up to the site in the workspace file list for a tenant whose workspace holds
the tag, cited with the page URL as "View at source", and absent from a tenant whose workspace
does not; downloads of a page stay refused (pages are never downloadable). Playwright: upload
from the console, release, the pages listed on the site detail, the site in the tenant's
library roll-up.

**P2SR01-06 Logging and audit catalogue.** Audit events `site.upload_staged`,
`site.upload_released`, `site.upload_rejected`, `site.upload_imported` and
`site.upload_failed`, classified `OPERATOR_ONLY_EVENTS` (the catalogue test fails on an
unclassified name). Their metadata: upload ID, site ID, mode, counts, codes; never a member
name, URL or title. Log lines from the inspection and the job: counts and codes only; the
static scan in `test_logging_policy` gains the new modules, and a runtime capture over a full
import with a deliberately odd member name and title asserts neither appears in any log line or
audit row. `app.content.uploads` is added to the modules the no-bodies-in-errors test checks
(the 422 body carries codes and member indices only).

**P2SR01-07 Design and policy documents.** In the same PR: architecture §6.2 gains a row
"Uploaded crawl" (editor uploads a ZIP of Markdown pages with front matter, the site's name,
URL and crawl date, declares the crawl honoured robots and TDM; reviewer releases; worker
imports as pages of the site; a later ZIP supersedes by URL, full or partial); §6.4 gains a
paragraph that for an uploaded crawl the robots, TDM and `noai` checks are **the uploader's
declaration, recorded per upload and released by a reviewer, not a check the platform makes**
(owner decision D3, Oct 31, 2026), and that `allow_decision = 'declared'` marks such sites.
`policy-content-sourcing.md` §4.2 gains the same rule and the evidence table a line "Uploaded
crawl declaration (robots, TDM, noai): `site_uploads.declared_robots_honoured`, release audit".
`risk-register.md` gains a row for a declaration made in error (an uploaded site whose owner
had reserved rights), mitigated by the takedown path and the reviewer's release.
`records-of-processing.md` notes the upload as a source of the same category as crawled pages.
Nothing is published to tenants; the privacy notice already covers crawled public pages.

**P2SR01-08 Release checks.** On the Instance, by the deploy script: the migration; the full
suite with the database; a synthetic ZIP from `packages/eval/fixtures/uploads/` uploaded
into `sample-web` on the internal tenant, released, imported, one page cited by a question on
the internal workspace with "View at source" showing the page URL; a second `partial` ZIP
with one changed and one new member, the superseded label on the first citation; a `full`
ZIP missing one page, that page withdrawn and its excerpt blanked; the site then withdrawn
and reinstated (P1c-14, P2A-12 a) with its pages behaving as a crawled site's do; log and
audit capture checked for names; eval set v1 unchanged (no prompt or retrieval change) and
not rerun unless the suite shows a retrieval difference. Findings in
`phase-2sr01-findings.md`; a short independent review as in Phase 1c §5.2, scoped to the
import and the logging items.

## Decisions

| # | Decision | Alternative | Applies to |
| --- | --- | --- | --- |
| D1 | **Taken, Oct 31, 2026. Per-page metadata from YAML-style front matter** in each file (`url` required, `title` and `date` optional). | A manifest file in the ZIP; URLs derived from member paths. Not now (backlog). | The ZIP, P2SR01-02 |
| D2 | **Taken, Oct 31, 2026. An uploaded crawl is a site with pages**, `origin = 'upload'`, schedule fixed to `none`; each member is a `site_pages` row and a register row. | Standalone Markdown sources with no site. Rejected: loses site-level withdrawal, reinstatement, roll-up and supersession by URL. | P2SR01-01, P2SR01-03 |
| D3 | **Taken, Oct 31, 2026. Declaration only, no network check.** The uploader declares that the crawl honoured robots.txt, the TDM reservation and page-level `noai` directives; the platform records the declaration per upload, the reviewer releases, and `allow_decision` reads `declared`. **Note for the owner:** this diverges from the compliance guide's "if a site has reserved rights in a machine-readable way, do not crawl it", which the live crawler enforces itself; P2SR01-07 records the divergence and the risk-register row. A domain-level re-check at release (one fetch of `robots.txt` and the start URL's headers, as `SiteCrawler.check` does) remains available as a later item and would need no schema change. | Re-check the domain at release, with or without the declaration. | P2SR01-01, P2SR01-03, P2SR01-07 |
| D4 | **Taken, Oct 31, 2026. Content console and CLI; editor uploads, reviewer releases.** | CLI only; the operator console (rejected, as decision D4 of Phase 2A kept content actions out of operator pages). | P2SR01-05 |
| D5 | **Taken, Oct 31, 2026. The uploader chooses full or partial per upload**, default partial, the choice audited and the withdrawal count shown before release. | Always full (as the live crawler); never withdraw on upload. | P2SR01-04 |
| D6 | **Taken, Oct 31, 2026. Limits 200 MB per ZIP, 2,000 Markdown members, 5 MB per member**, plus a 500 MB uncompressed total of this spec's own. | 500 MB / 5,000 / 10 MB with streaming to disk; 50 MB / 500 / 2 MB. | The ZIP, P2SR01-02 |
| D7 | **Proposed: every upload is released by a reviewer**, including uploads to a site already approved. A live crawl's pages are whatever the site publishes within the scope rules the reviewer approved; an upload's pages are whatever the editor put in the ZIP, so each batch is a reviewed act. The release is one click with the report in front of the reviewer. | Site approval covers later uploads, as it covers later crawls (P1b decision 8). Smaller, but an editor alone could then put content into RAGFlow. Not recommended. | P2SR01-03 |
| D8 | **Proposed: no HTML snapshot for an uploaded page**; the staged Markdown (by hash, as every file is) is the provenance copy, `snapshot_path` stays null, and the site detail says "uploaded, no snapshot". | Accept an optional `.html` sibling per member as the snapshot. More ZIP rules and the HTML is untrusted; not now (backlog). | P2SR01-03 |
| D9 | **Proposed: `fetched_at` is the upload's crawl date** (midnight UTC) on every page of that upload, shown as the fetch date in the console and the file list; the upload's own timestamp is `uploaded_at`. | Use the upload time as the fetch date. Rejected: the crawl date is the fact the owner asked to record. | P2SR01-03 |
| D10 | **Proposed: one pending upload per site at a time**, and a second ZIP for a site waits until the first is imported, rejected or failed. | Queue several. Not needed for a hand-run process. | P2SR01-02 |

## Open items for the owner

- **D7 to D10**: confirm or change before the build session starts.
- **Declaration text** (D3, P2SR01-05): the sentence the editor ticks. Proposed: "I confirm
  that this crawl of `<host>` was made on `<crawled_on>` honouring the site's robots.txt, its
  text-and-data-mining reservation if any, and page-level noai and noindex directives, and that
  the pages are public and were fetched without signing in." Counsel may want to see it.
- **Licence basis for uploaded sites**: the site form's free-text basis, as for crawled sites
  (`public_web` once P1b-19 step 2 adds the enumerated kinds). No change proposed.
- **Which tool produces the ZIPs**, so the fixture ZIPs in `packages/eval/fixtures/uploads/`
  mirror its front matter (key names and date format) and the owner needs no conversion step.
  If the tool emits other key names (`source_url`, `published`), P2SR01-02 accepts them as
  aliases of `url` and `date`; say which.
- **Phase 2A dependency**: this spec assumes the Phase 2A release (P2A-14) is on `main` before
  the build starts, so the inherited pause (P2A-03) and reinstatement (P2A-12 a) are in place.
  If the build must start earlier, it branches from the Phase 2A integration branch.

## Session plan

One build session on `claude/p2sr01-uploaded-crawls` off `main` after the Phase 2A release:
P2SR01-01 to P2SR01-04 first (register, inspection, release and import, second upload), then
P2SR01-05 and P2SR01-06, then P2SR01-07 in the same PR, then the release session for
P2SR01-08 with findings and the short independent review. Builder questions go to
`phase-2sr01-findings.md` §1 for the owner, as in Phase 2A.
