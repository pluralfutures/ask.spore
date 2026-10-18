# Sample corpus manifest — `manifest.csv`

Implemented by `ask-spore ingest-manifest` (P0-11, `apps/api/app/content/manifest.py`); the licence basis vocabulary is enforced as proposed below unless the owner amends it. Two details the command fixes: `canonical_url` is required unless `licence_basis` is `own-work`, and a `site` row without `max_pages` crawls at most 50 pages.

Format for the manifest that drives batch ingestion of the Phase 0 sample corpus (spec items P0-09, P0-10, P0-11). The columns map one-to-one onto the `ask-spore ingest` and `ask-spore crawl` flags and onto the `sources` table (P0-05).

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

## Rules

- UTF-8, comma-separated, header row exactly as above, one row per document or site.
- Quote any field containing a comma. Spreadsheet exports do this automatically.
- File names must be unique across the whole tree. Eval items reference files by name until source register IDs exist after ingestion.
- The batch command validates every row before uploading anything and reports all errors at once.

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
