# Sample corpus manifest — `manifest.csv`

Implemented by `ask-spore ingest-manifest` (P0-11, `apps/api/app/content/manifest.py`; since Phase 1b through the source register and the job queue, see "Register, approval and the worker" below); the licence basis vocabulary is enforced as proposed below unless the owner amends it. Columns are matched by header name in any order. Two details the command fixes: `canonical_url` is required unless `licence_basis` is `own-work`, and a `site` row without `max_pages` crawls at most 50 pages.

Format for the manifest that drives batch ingestion of the Phase 0 sample corpus (spec items P0-09, P0-10, P0-11). The columns map one-to-one onto the `ask-spore ingest` and `ask-spore crawl` flags and onto the `sources` table (P0-05); since Phase 1b a `site` row maps onto the `sites` table (P1b-04, "Sites" below).

Status: proposal from the coding session, 2026-10-18. The licence basis vocabulary needs confirmation from the research lead before the team fills in rows.

## Folder layout

Folder layout is free; ingestion records each file by content hash, not by location. Recommended layout, organised by tag:

```
corpus/
  manifest.csv
  sample-reports/     third-party PDFs (deeper nesting by publisher or year is fine)
  sample-analysis/    own DOCX and PPTX
```

Crawled sites are rows in the manifest, not files.

The corpus and the manifest live on the Phase 0 Instance only. Never commit them: they contain real third-party documents (CLAUDE.md rule).

## Columns

| Column | Required | Values | Notes |
| --- | --- | --- | --- |
| `path` | yes for files | Relative path from the manifest's folder, e.g. `sample-reports/oecd/report-2024.pdf` | Empty for a crawled site. |
| `url` | yes for sites | Site root URL | Only for `type = site`. Empty for files. |
| `type` | yes | `pdf`, `docx`, `pptx`, `html`, `markdown`, `site` | Must match the file. `site` rows go to the crawler, not the uploader. |
| `tags` | yes | One or more tags separated by `;`, e.g. `sample-reports` | Must exist in `config/tags.toml` (Phase 0: `sample-reports`, `sample-analysis`, `sample-web`). A file with two tags is uploaded to both datasets. |
| `title` | yes | Free text | Shown in citations. |
| `publisher` | yes | Free text, e.g. `OECD` | Shown in citations. |
| `published_on` | yes | ISO date `YYYY-MM-DD` | Year only (`YYYY`) is accepted and stored as 1 January; mention it in `notes` if it matters. |
| `canonical_url` | yes for third-party | Publisher's own page for the document | Used as the citation link. Optional for own analysis. |
| `licence_basis` | yes | `public`, `open-licence`, `publisher-terms`, `own-work` | Proposed vocabulary; research lead to confirm or amend. |
| `language` | no | ISO 639-1, e.g. `en`, `de` | For spot-checking only; not used by retrieval in Phase 0. |
| `max_pages` | no | Integer | `site` rows only; caps the crawl. |
| `notes` | no | Free text | Anything the content editor wants recorded. Not sent to RAGFlow or the LLM. |
| `downloadable` | no (optional column) | `true` or `false`; empty means `false` | P1a-14, licence-gated downloads: `true` only where the licence permits redistribution from our domain (our own analyses; third-party files where the row's `licence_basis` records the permission). No permission letter is required, in the manifest or in the console's propose form (owner decision 10, Oct 22, 2026); a letter may still be attached to a source in the console. Only `pdf`, `docx` and `pptx` rows. Read for new sources, and for an already-ingested source when its row adds a tag (re-tagging, below; the change is audited); otherwise re-running the manifest does not change the flag, and the operator console does, audited. The column may be left out entirely, or placed anywhere. |

## Rules

- UTF-8, comma-separated, one row per document or site. The header row names the columns; their order is free (owner decision, Oct 20, 2026), since columns are matched by header name. All twelve columns from `path` to `notes` must be present (a column marked "no" may be left empty, not out); `downloadable` is the only optional column and may be anywhere or left out. Any other column name, or a column listed twice, is refused.
- PDF, DOCX and PPTX files are also copied to the API's content store (`[files] content_root`, named by content hash) for downloads. Re-running the manifest stores the copy of a file ingested before P1a-14.
- Quote any field containing a comma. Spreadsheet exports do this automatically.
- File names must be unique across the whole tree. Eval items reference files by name until source register IDs exist after ingestion.
- The batch command validates every row before uploading anything and reports all errors at once.
- Re-tagging: a row whose file is already ingested (same content hash) but whose `tags` include tags the source lacks uploads and parses the file again into each new tag's dataset (RAGFlow cannot link one document into a second dataset), adds the tags to the source and reports the row as `retagged`; a failure there removes only the new documents and leaves the source as it was. Since Phase 1b a re-tag needs a reviewer: without `--approve-as` the row reports `retag_pending` and nothing changes.
- A file with new content at the `canonical_url` **and with the `title`** of exactly one ingested source is that source's new version (owner decision 3, Oct 23, 2026, P1c-14): with `--approve-as` it is approved and, once ingested, replaces the old source as below; titles are compared ignoring case and runs of spaces. So a corrected file is re-ingested by re-running its manifest row with the same link and title.
- A file with new content at the `canonical_url` of an ingested source under **another title** (or at a link that two ingested sources share under that title) is **not** treated as that source's new version automatically (owner decision 4, Oct 22, 2026; this replaces the Phase 1b A1 rule that a canonical link identifies one document). The row is proposed and flagged "possible replacement of <source>"; even with `--approve-as` it stays `proposed` (error code `possible_replacement`) until a reviewer chooses in the console, or with `ask-spore sources approve <source_id> --as <email> --replace <old source_id>` or `--keep-both`. With "replace", once the new file is ingested the old source is withdrawn from every dataset and its citations show as "superseded"; with "keep both" both stay. A publisher's landing page may therefore be the link of several documents. The manifest has no `replaces` column (decision 4).

## Register, approval and the worker (Phase 1b)

Every row goes through the source register (P1b-01, P1b-02): it is **proposed**, and nothing reaches RAGFlow until a content reviewer **approves** it. Approval queues a job; the `worker` Compose service ingests it.

```
ask-spore ingest-manifest corpus/manifest.csv --approve-as owner@example.org --wait
```

- `--approve-as <email>`: a content reviewer (an internal user with the `content_reviewer` role) approves every proposal of the run, audited. Without it the rows stay `proposed` for a reviewer (`ask-spore sources approve <source_id> --as <email>`).
- `--propose-as <email>`: the content editor proposing; defaults to the `--approve-as` user. When that is the same person (the owner holds both roles, owner decision Oct 21, 2026) the approval is recorded as a self-approval.
- `--wait`: wait for the worker and report what the jobs did. Without it the run ends once the jobs are queued.
- Files are staged under `[files] content_root` by content hash at proposal, so the worker can read them; the original file names are not kept.
- A file whose content was withdrawn after a takedown request is not proposed again (`failed`, error code `taken_down`).

Row statuses in the summary (log lines and `--summary` CSV):

| Status | Meaning |
| --- | --- |
| `proposed` | Recorded; waits for a reviewer. With error code `possible_replacement`: the file sits at the canonical link of an ingested source under another title, and the reviewer chooses replace or keep both. |
| `retag_pending` | Already ingested; the row adds tags, which needs a reviewer. Nothing recorded. |
| `queued` | Approved; the worker will ingest it (without `--wait`). |
| `ingested` | Ingested (with `--wait`). |
| `retagged` | Linked into the new tags' datasets (with `--wait`; chunk count 0, jobs record no counts). |
| `duplicate` | Same content already ingested in every listed tag; nothing to do. |
| `failed` | With an error code: the job's (`parse_failed`, `no_chunks`, `ragflow_…`), `taken_down`, or `needs_retry` (a failed source waiting for a reviewer's `sources retry`). |

Site rows report `ok`, `failed`, or the first waiting status of their pages.

## Sites (Phase 1b, P1b-04)

A `site` row registers the site in the `sites` table (the content console's Sites page), with the row's `title` as the site's name, its `publisher`, `licence_basis`, `tags` and `max_pages`; the row's `published_on` and `canonical_url` are not used for sites (each page's date comes from its own metadata, and its URL is its canonical link). With `--approve-as` the reviewer approves the site, which queues a `crawl_site` job for the worker; a site approved earlier gets a crawl now. Without it the row reports `proposed` until a reviewer approves the site in the console. A rejected site fails with `site_rejected`. With `--wait` the run waits for the crawl and then for the pages it queued.

`ask-spore crawl <url> --tag … --max-pages … --licence … [--publisher …] [--name …] [--allow /path/*] [--deny /path/*] [--schedule none|weekly|monthly] [--approve-as …] [--wait]` does the same for one site. The `--out-dir` and `--crawl-dir` flags of Phase 0 are gone: pages are staged under `[files] content_root`, with their raw HTML snapshot.

The worker's crawl honours robots.txt, the crawl delay and the TDM reservation (the site's allow decision), stays within the scope rules and the page budget, waits at least a second between requests to one host, skips special-category pages unless a reviewer whitelists their path, takes publication dates from explicit page metadata only, re-ingests changed pages (the new version replaces the old one) and withdraws pages that are gone. Each page is a register row in the reviewer's name: the reviewer's approval of the site covers its pages.

Source register states: `proposed → approved → ingested → withdrawn`, plus `failed` (a reviewer retries it) and `rejected` (a reviewer declined the proposal, with a note).

## Withdrawal and takedown (Phase 1b, P1b-03)

- `ask-spore sources withdraw <source_id> --as <reviewer email> --reason "…" [--wait]` queues the withdrawal: the document is deleted from every dataset, its citations in users' history are flagged **withdrawn**, the register row is marked `withdrawn` with the reason and date, our stored copy is deleted, and cached answers that cite it are purged in every tenant.
- `ask-spore sources takedown <source_id> --as <reviewer email> --reference <ref> --requested-on YYYY-MM-DD [--licence-breach] [--licence-grounds]` puts a source on the takedown queue: due 10 working days (Monday to Friday) after the request, or the same day for a licence breach we find ourselves. `--licence-grounds` marks a request on licence grounds (a licence breach always is). The withdrawal is a separate reviewer step.
- In the chat history a citation of a re-ingested source is labelled **superseded**, of a withdrawn source **withdrawn**. The stored excerpt stays, except after a takedown on licence grounds: the excerpt is the licensed text, so the withdrawal blanks it (for that source and the earlier versions it replaced) and the citation keeps its title, publisher, link and the "withdrawn" label (owner decision 5, Oct 22, 2026).

## Example

```csv
path,url,type,tags,title,publisher,published_on,canonical_url,licence_basis,language,max_pages,notes
sample-reports/oecd/digital-economy-outlook-2024.pdf,,pdf,sample-reports,Digital Economy Outlook 2024,OECD,2024-05-14,https://www.oecd.org/en/publications/oecd-digital-economy-outlook-2024.html,publisher-terms,en,,
sample-reports/eurostat/ict-usage-2024.pdf,,pdf,sample-reports,ICT usage in enterprises 2024,Eurostat,2024-12-02,https://ec.europa.eu/eurostat/web/products-eurostat-news/...,open-licence,en,,"Has large tables, check parsing"
sample-analysis/battery-storage-outlook.pptx,,pptx,sample-analysis,Battery storage outlook 2030,Plural Futures,2025-03-01,,own-work,en,,
sample-analysis/battery-storage-memo.docx,,docx,sample-analysis;sample-reports,Battery storage memo,Plural Futures,2025-03-10,,own-work,en,,"Two tags on purpose"
,https://www.example-thinktank.org/,site,sample-web,Example Thinktank site,Example Thinktank,2025-10-01,https://www.example-thinktank.org/,publisher-terms,en,50,
```

## Phase 0 corpus targets (from the build spec)

- 30 or more third-party PDFs
- 10 or more own DOCX or PPTX files
- 2 crawlable sites
