# Phase 2B Findings

Oct 27, 2026. Build record of Phase 2B (`phase-2b-build-spec.md`), kept like
`phase-2a-findings.md`: what was checked on the Instance, where the result differs from the
spec, and why. Metadata only: no query, answer, token, key or email address is recorded
here. The only document text quoted comes from the synthetic fixtures. RAGFlow IDs are not
recorded.

## 1. P2B-06 RAGFlow parse of Markdown and plain text

Run Oct 27, 2026 on the Instance's RAGFlow (`infiniflow/ragflow:v0.27.2`, the pinned
version), from inside the `api` container. The client was the app's own `RagflowClient`, so
the service key stayed in that container's environment and the base URL came from
`config/models.toml`. The app was not changed: this branch was not deployed, migration 0071
was not run, and no client document was used.

### What was run

- **Fixtures** (synthetic, `packages/eval/fixtures/text_files/`):
  - `marrow-fen-water-survey.md`: 7.3 KB, three heading levels, a five-row GFM table,
    bullet and numbered lists, and non-ASCII text (accented Latin, Ø, Ą, Greek, Cyrillic,
    Chinese, `₂`, `°`, `€ £ ¥`, curly quotes and an emoji). No BOM, LF line endings.
  - `quillan-ferry-timetable-note.txt`: 6.4 KB, plain paragraphs, a table aligned with
    spaces, the same non-ASCII set, a UTF-8 BOM and CRLF line endings.
  - Inline only, not committed: a three-line Markdown file holding one image reference to
    an `.invalid` host.

  The branch's `check_file_content` accepts both fixtures: `.md` declared as
  `text/markdown`, and `.txt` declared as `text/plain` or with no media type.
- **Temporary tag.** A tag here is a RAGFlow dataset plus a `datasets` row. Registering a
  real tag needs `config/tags.toml` in the live tree and the `text` source type, which needs
  migration 0071. So the "tag" was a bare RAGFlow dataset, `ask-spore-tmp-p2b06-parse-check`,
  created with the production embedding model (`BAAI/bge-m3@Builtin`). It was not in
  `tags.toml` and had no `datasets` row, so no workspace or package could reach it.
- **Two runs, one for each way a dataset is set up:**
  1. A dataset created with `naive`.
  2. A dataset created with `paper` (the default of every client tag and of `sample-reports`),
     with each document switched to `naive` by `set_document_chunk_method`. This is what
     ingestion does for `chunk_method_by_type`.

  Both runs produced identical chunks: the same text and the same positions.
- **Each run:** upload, parse, list the chunks, then three retrieval calls with the app's
  flags (keyword extraction, knowledge graph, TOC and cross-language all off). The dataset
  was then deleted.

### Results

| | `.md` | `.txt` |
|---|---|---|
| Parse | `DONE`, about 15 s (mostly embedding) | `DONE`, about 16 s |
| Chunks / tokens | 5 / 1,873 | 3 / 1,544 |
| Chunk size | merged up to `chunk_token_num` 512, delimiter `\n` (RAGFlow default `parser_config`) | same |
| Headings | Kept in the text as `#`, `##`, `###` lines. A chunk never ends on a short heading: the heading is merged with the paragraph that follows. A chunk that starts mid-document carries no parent heading (e.g. chunk 4 starts at `### A.4` with no `Appendix A`). | n/a; an upper-case title line stays in its chunk as plain text |
| Tables | The GFM table is converted to an HTML `<table>` (`<thead>`, `<th>`, one `<tr>` per row). All five rows survive, in one chunk, together with the paragraph after it. | The space-aligned table survives line by line with its spacing, inside one chunk. |
| Lists | Kept as `-` and `1.` lines | n/a |
| Blank lines | Removed; paragraphs are joined with a single `\n` | Removed; each chunk starts with one `\n` |
| BOM / CRLF | n/a | BOM removed, CR removed (`decode_text` reads the BOM as `utf-8-sig`) |
| Non-ASCII | All 22 probe strings present and unchanged, text NFC, emoji kept | same |
| Positions | `[[n, n-1, n-1, n-1, n-1]]` for chunk n (1-based) | same |
| LLM calls during parse | none: `auto_keywords` 0, `auto_questions` 0, `llm_id` empty; RAGFlow has no default vision model (logged "No visual model detected") | none |

Retrieval found the right chunk for each question. The nitrate question returned the
table chunk first (similarity 0.33). The timetable question returned the text chunk with
the timetable (0.33).

### Pages and citations

**The finding R14 no longer describes what RAGFlow returns.** The Phase 0 finding said
Markdown chunks come back with a pseudo-position `[[1, 0, 0, 0, 0]]`. On v0.27.2,
Markdown and text chunks carry a running chunk index instead: `page_or_slide()` reads pages
1, 2, 3… across one file.

The app is still correct:

- `ContextChunk.page_or_slide` (`app/chat/context.py`) returns `None` for any type outside
  `PAGED_SOURCE_TYPES` (`pdf`, `pptx`). Both the prompt attribute and the stored citation
  (`orchestrator._citation`, the `citations` row) read that property.
- `pageLabel()` in the web app returns no page label for `null`.

So a `.md` or `.txt` citation shows publisher, title and date with no page, as HTML does.
The filter matters more than R14 suggested: without it, a chunk would show "p. 3" for a
file that has no pages.

### Remote images in Markdown are fetched by RAGFlow

RAGFlow's Markdown parser (`rag/app/naive.py`, `Markdown.load_images_from_urls`) fetches
every `http(s)` image reference while it parses. The inline probe file's image triggered a
lookup (`SSRF guard could not resolve hostname=…invalid`). The guard refuses private,
loopback and link-local addresses, but allows public ones. The `ask-spore-dev_ragflow`
network is not `internal`, so RAGFlow can reach the internet.

As a result, an uploaded `.md` file with `![](https://…)` makes the Instance request that
URL during ingestion. This exposes the server's IP address and the time of ingestion to
whoever controls the host. With no vision model configured, the image itself goes no
further. Crawled pages, stored as Markdown, already take the same path today.

Not tested against a public host, to avoid sending any request out.

An image reference that is not `http(s)` is opened as a file path inside the RAGFlow
container (`Image.open(url)`), so a local path is read too. It goes no further while no
vision model is set.

**Decision (owner, Oct 27, 2026; spec owner decision 6): uploaded Markdown with an image
reference is refused.** `check_file_content` refuses any `![..](..)`, `![..][..]`, `<img>`
or `src=` in a Markdown upload or manifest ingest with `image_reference` (code only, no
file text). The patterns cover everything RAGFlow's extractor matches. Plain `[text](url)`
links are still accepted, and `.txt` is not checked because RAGFlow's text parser loads
nothing. Crawled pages still go through RAGFlow's image loading; that stays in `backlog.md`.

### Decision: "naive" stays

`config/tags.toml` is unchanged. In RAGFlow v0.27.2, `naive` is the only chunk method
with a Markdown and a text branch:

- **Markdown:** `naive` is heading-aware. It splits at lines, keeps headings in the text,
  never ends a chunk on a short heading, and keeps a table whole in one chunk.
- **Plain text:** `naive` is size-based, splitting at `\n` up to 512 tokens.

That is the spec's "Markdown by headings, text by size", as closely as RAGFlow offers it.
None of the other methods fits better:

- `one` makes the whole file one chunk.
- `book`, `laws`, `manual`, `paper` and `presentation` have no Markdown or text branch, or
  are for other layouts.

Two limits to know (not changed here):

- A chunk from deep in a long Markdown file does not repeat its parent headings. Retrieval
  on a section's title can miss its later chunks.
- A Markdown table reaches the model as HTML markup inside an untrusted-source block. The
  model reads it, but it costs more tokens than the pipe form. If that matters for long
  tables, it is a RAGFlow parser setting to look at later, not a reason to change the method.

### Cleanup

- Both temporary datasets were deleted with `DELETE /api/v1/datasets`, and their documents
  went with them.
- After each run, listing the dataset's documents returned RAGFlow error 102 (no such
  dataset).
- `list_datasets` showed no dataset named `ask-spore-tmp-…`. An earlier attempt failed
  before printing because of a page-size error; its dataset was deleted by the same
  `finally` block, and the same listing confirmed it.
- No row was written to the app database. `config/` in the live tree was not touched.
- RAGFlow's own log keeps the fixture file names and the `.invalid` hostname. That log
  holds only synthetic data.

## 2. Visual baselines for P2B-01 to P2B-05

Generated Oct 27, 2026 in the pinned Playwright image (`run-in-image.sh`, `v1.63.0-noble`,
digest `eff16c30…`), with `pnpm test:visual --update-snapshots`, and reviewed by eye.

- **New scenarios.** None had been added with the build, so these were added now:
  - `06k-home-summary`: the "Sources in this workspace" card, with the fixture of
    `workspaceSummary.spec.ts`;
  - `09e-chat-wide-table`: the wide table of `markdownTable.spec.ts`, with a citation in a
    cell.

  Both are in `SCENARIOS`, so the axe, layout, keyboard, buttons and forms specs run on them
  too (12 tests, all pass). The static pages `22-legal-index`, `22b-legal-privacy` and
  `22c-security-disclosure` are a separate list in `visual.spec.ts`, because the app-only
  specs do not apply to plain HTML pages.
- **Changed baselines** (both widths):
  - `06` and `06b`: the search box above the list.
  - `08`, `08b` to `08e`, `09`, `09b` and `09c`: the rename button next to the chat title,
    which moves the content down a few pixels. On the phone, the 44 px button makes the
    title row about 20 px taller.

  Nothing else differed.
- **Consent page.** `05-consent-first` did not change. The scenario's consent text is
  synthetic and has no table, so the table look of P2B-01 is covered by `09e` and
  `22b-legal-privacy` instead.
- **Review notes.**
  - The legal pages and `/security-disclosure` use the app's header, card, Lato and footer
    at both widths.
  - At 390 px, the privacy notice's four-column tables scroll inside their own frame and the
    page does not. Nothing on screen shows that the table scrolls; the clipped column is the
    only cue.
  - On the phone, the summary card sits below the first screen while the welcome block is
    shown. That is the same place the recent conversations already sat.
- **Checks.**
  - `pnpm lint` and `pnpm typecheck` pass.
  - A second visual run without updating passes all 144 tests, including the negative
    background-colour case.
