# Phase 0 Sample Corpus: Ingestion and Spot-Check Checklist (P0-11)

For the content editor, with an engineer at hand for the first run. It covers ingesting the sample corpus (30+ third-party PDFs, 10+ own DOCX/PPTX files, 2 crawled sites) on the Phase 0 Instance, spot-checking the parsing, and recording what you find in `design/specs/phase-0-findings.md` (section 4, plus the measurements in R2 and P0-20).

The tooling was verified end to end against the Compose RAGFlow with the synthetic files in `packages/eval/fixtures/corpus/`. Section 4 of the findings lists what the parsers did with those files, which tells you what to look for.

## 0. Before you start

Licences come first (Compliance guide, "Content licensing and crawling"):

- [ ] Every PDF has a recorded licence basis (licence name or permission-letter reference) that allows text-and-data mining and AI use. If you are in doubt, leave it out.
- [ ] For each site to crawl, the site terms have been read and allow it. The crawler checks robots.txt and the machine-readable TDM reservation itself, but it cannot read terms of use.
- [ ] The corpus contains no client documents and no special-category personal data.
- [ ] The files sit on the Instance in one directory, e.g. `/srv/corpus/`, never in the repository.

Instance setup (engineer):

- [ ] `infra/ragflow/.env` from `.env.example` with real passwords; `TEI_MAX_BATCH_TOKENS=4096` (findings R2).
- [ ] `sudo sysctl -w vm.max_map_count=262144` (Elasticsearch).
- [ ] At least 20 GB free disk after pulling images. Elasticsearch stops accepting chunks below 3 GB free (findings R12).
- [ ] `docker compose -f infra/compose.dev.yml up -d`. Register the first RAGFlow account in the UI, then set `REGISTER_ENABLED=0` and restart `ragflow`.
- [ ] Create a RAGFlow API key (avatar → API) and put it in the repository-root `.env` as `RAGFLOW_API_KEY`.
- [ ] The RAGFlow UI port is firewalled to the team's IPs (findings R3).
- [ ] Datasets exist and are mapped:

  ```
  docker compose -f infra/compose.dev.yml run --rm api ask-spore datasets sync
  ```

  Every tag should log `"status":"created"` the first time and `"ok"` after that. Anything else (`mismatch`, `missing`, `ambiguous`) needs an engineer.

## 1. Dry run with the synthetic files

Run the synthetic files through once before the real corpus. It checks the whole chain in a few minutes.

```
CORPUS=packages/eval/fixtures/corpus
docker compose -f infra/compose.dev.yml run --rm -v "$PWD/$CORPUS:/corpus:ro" api \
  ask-spore ingest /corpus/tidewater-offshore-wind-2026.pdf --tag sample-reports \
  --title "Tidewater Offshore Wind Outlook 2026" \
  --publisher "Fictional Institute for Coastal Energy" --licence "synthetic test fixture"
```

- [ ] It logs `"event":"ingest.result","status":"ingested"` with a non-zero `chunk_count`.
- [ ] The document is visible in the RAGFlow UI under dataset `ask-spore-sample-reports`.

## 2. Ingest the corpus

With a `manifest.csv` (format: `design/specs/corpus-manifest.md`), one command ingests the whole corpus. It validates every row against `config/tags.toml` and the file tree first and uploads nothing if any row is invalid; re-running it is safe (files already ingested report `duplicate`). It logs one `manifest.row` line per row (manifest line, status, chunk count, wall time, source ID) and `manifest.summary` totals per status; `--summary` writes the same table to a CSV file:

```
docker compose -f infra/compose.dev.yml run --rm -v /srv/corpus:/corpus:ro api \
  ask-spore ingest-manifest /corpus/manifest.csv --check     # validate only
docker compose -f infra/compose.dev.yml run --rm -v /srv/corpus:/corpus:ro -v /srv/crawl:/crawl api \
  ask-spore ingest-manifest /corpus/manifest.csv --summary /crawl/summary.csv --crawl-dir /crawl
```

Otherwise, run one command per document. Mount the corpus read-only:

```
RUN='docker compose -f infra/compose.dev.yml run --rm -v /srv/corpus:/corpus:ro api ask-spore'
```

Third-party PDFs (tag `sample-reports`, parsed with `paper`):

```
$RUN ingest /corpus/reports/<file>.pdf --tag sample-reports \
  --title "<title as published>" --publisher "<publisher>" \
  --published-on <YYYY-MM-DD> --licence "<licence or permission ref>" \
  --canonical-url "<public link users will see>"
```

Own analysis (tag `sample-analysis`: DOCX parsed with `naive`, PPTX with `presentation`):

```
$RUN ingest /corpus/analysis/<file>.pptx --tag sample-analysis \
  --title "<title>" --publisher "<our name>" --licence "own work" --published-on <YYYY-MM-DD>
```

Crawled sites (tag `sample-web`). The rendered Markdown pages are written to `--out-dir` for review. It has to be a mounted directory, or the files disappear with the container, and the API container runs as uid 10001:

```
sudo install -d -o 10001 /srv/crawl
docker compose -f infra/compose.dev.yml run --rm -v /srv/crawl:/crawl api ask-spore \
  crawl https://<site>/ --tag sample-web --max-pages 50 \
  --publisher "<site owner>" --licence "<terms reviewed on YYYY-MM-DD>" --out-dir /crawl/<site>
```

- [ ] `crawl.finished` shows `"status":"ok"`. `tdm_reserved` or `robots_disallowed` means the site has opted out; record it and pick another site. `crawl.skipped` lines count the pages skipped and why.
- [ ] A document already ingested logs `"status":"duplicate"`. That is fine.
- [ ] A failure logs `"status":"failed"` with an `error_code`. The full error is stored on the source row (query in section 4), and the failed document has already been removed from RAGFlow.

Several tags: repeat `--tag`. The document is then stored once per tag's dataset.

## 3. Spot-check parsing in the RAGFlow UI

Check **five documents per type**: PDF, DOCX, PPTX and crawled page (20 in all). Choose the hardest: long tables, multi-column layouts, charts, scanned pages, slide notes, footnotes. In the RAGFlow UI open the dataset, then the document, then its chunks, and compare them with the original file open beside them.

For each document, tick or note:

- [ ] **Text fidelity.** Words are not glued together or split. Characters are not misread (watch for l/I, 0/O, ligatures) or lost. (Synthetic PDF: "Supply-chainbottlenecks", "FlCE".)
- [ ] **Reading order.** Multi-column pages read column by column. Sidebars and pull-quotes do not cut into sentences.
- [ ] **Tables.** Tables come out as tables, with header rows and the right cell values. A table split across pages is noted.
- [ ] **Figures and charts.** The caption is kept and attached to the right figure. Note whether chart data is lost: it usually is, and then the numbers are only retrievable if the text repeats them.
- [ ] **Headers, footers, page numbers.** Running headers, footers and "Page n of m" do not repeat in every chunk.
- [ ] **Headings.** Headings stay with their section; a heading is not stranded at the end of the previous chunk. (Synthetic PDF: a heading moved across a page break.)
- [ ] **Slides (PPTX).** One chunk per slide, slide numbers right, text boxes and tables included. **Speaker notes are not ingested** (synthetic deck): note any deck whose substance is in the notes.
- [ ] **DOCX.** Paragraph breaks are kept. (Synthetic note: paragraphs ran together.) Lists and tables are intact.
- [ ] **Crawled pages.** Only the article text, without navigation, cookie banners, "related articles" or footers. One page per file in `/srv/crawl/<site>`.
- [ ] **Chunk size.** Chunks are neither a single line nor several pages; the default is about 512 tokens.
- [ ] **Language.** Non-English text is intact (accents, umlauts).
- [ ] **Page numbers.** The page shown for a PDF chunk matches where the text is in the PDF.

Record each problem in findings section 4 as one row: type and method, document (source ID, not the file name if that is sensitive), what is wrong, and how much it matters. Use the same table as the synthetic observations.

## 4. Check the register and collect measurements

The engineer runs these against the app database:

```
-- every source, status and chunk count; failures with their error
SELECT type, status, count(*), sum(chunk_count) FROM sources GROUP BY 1, 2 ORDER BY 1, 2;
SELECT id, type, title, error FROM sources WHERE status = 'failed';

-- licence basis present for every source (Compliance guide checklist)
SELECT id, title FROM sources WHERE coalesce(trim(licence_basis), '') = '';

-- parse throughput: wall time from registration to result, per type
SELECT type, count(*),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM updated_at - created_at)) AS median_s,
       max(extract(epoch FROM updated_at - created_at)) AS max_s
FROM sources WHERE status = 'ingested' GROUP BY type;
```

- [ ] No source is left in `ingesting`; that would mean a CLI run was killed. Re-run that document.
- [ ] Every failure is understood: re-ingested after a fix, or excluded with a reason recorded.
- [ ] **Memory (R2, P0-20).** While the largest PDFs parse, run `docker stats --no-stream` and record the peak for `ragflow-tei`, `ragflow-es`, `ragflow` and the total. Compare with the build-host figures in R2; the Instance has 8 vCPU.
- [ ] **Throughput (P0-20).** Record the median and maximum parse time per type from the query above, and the total time for the corpus.
- [ ] **Disk.** Record `df -h` before and after ingestion.

## 5. Done when

- [ ] At least 30 PDFs, 10 DOCX/PPTX and 2 crawled sites have `status = 'ingested'`.
- [ ] 20 documents spot-checked, problems recorded in findings section 4.
- [ ] Memory, throughput and disk figures recorded for R2 and P0-20.
- [ ] A short note in findings section 4 says whether parsing is good enough for Phase 1 per type, and what to change if not (chunking method, a pre-conversion step, or excluding a document class).
