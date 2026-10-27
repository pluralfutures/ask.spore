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
nothing.

**Decision (owner, Oct 27, 2026; spec owner decision 7): crawled and fetched pages are closed
in two layers.** (1) `strip_image_references` (`app/content/markdown.py`) takes every image
reference out of a crawled page's Markdown (`crawler.render`) and of a fetched `.md` page
(`from_fetched`) before it is stored or hashed; the alt text stays as plain text, and any line
the patterns still match is dropped, so the result passes the same check an upload must pass.
(2) The `ragflow` Compose network (`infra/ragflow/docker-compose.yml`) is `internal: true`:
RAGFlow, its stores and TEI reach each other and the API and workers, and nothing else, so a
parser that tries a URL has no route. Docker publishes no port for a container that is only
on an internal network, so the loopback web UI now runs through `ragflow-ui`, a Caddy
reverse proxy (the image already pinned for the public proxy) on both the internal network
and a second, ordinary one. `tests/test_compose_egress.py` fails if a tier service joins a
network with internet access or publishes a port.

**To check on the Instance at release (not testable in the build session, no Docker):**
`docker compose up -d` recreates the `ragflow` network, which restarts the tier briefly;
then (a) from inside the `ragflow` container an outbound request fails (`curl -m 5
https://example.org`); (b) the API and worker still reach `http://ragflow:9380` (a parse of a
PDF, a DOCX, a `.md` and a `.txt` completes); (c) a restart of the tier comes up healthy with
no download attempt in its logs (the DeepDoc models and the embedding model are on disk);
(d) the SSH tunnel to `127.0.0.1:${RAGFLOW_UI_PORT}` still opens the UI and a document page.
If (c) shows a start-up download, the model must be baked into a volume first; do not remove
`internal: true` without an owner decision.

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

## 3. Instance checks for the internal RAGFlow network (handoff brief)

Run Oct 27, 2026 on the Instance (Docker 29.9.1, Compose v5.6.0) for `phase-2b-handoff.md`, at
`d07ebf2`. Every check ran in a scratch Compose project, `p2bcheck`: a copy of the branch,
its own volumes, generated passwords, loopback ports 15432/16379/18000/18080, a fresh
RAGFlow account on `example.org` and synthetic fixtures only. The live stack, its
database and its RAGFlow were not touched. The scratch project was removed at the end:
containers, networks, its 7 volumes and its 3 built images, all named explicitly; a
listing found nothing left.

### Needs an owner decision

1. **`deploy.sh` cannot apply this change as it stands, and would leave RAGFlow down.**
   - Step 9 runs `up -d ragflow caddy`. Changing the network's `internal` flag makes
     Compose stop the tier and remove the `ragflow` network, which fails while `api` and
     `worker` are attached: `network … has active endpoints`. The command exits 1 with the
     whole tier stopped, and the API keeps running without retrieval. This was reproduced in
     the scratch project.
   - Even with the network recreated, Compose re-attaches the unchanged store containers
     without their service-name aliases. `ragflow-mysql`, `ragflow-es`, `ragflow-minio` and
     `ragflow-redis` stop resolving, and `ragflow` crash-loops ("Can't connect to MySQL
     server on 'ragflow-mysql' … name resolution"; 14 restarts in 7 minutes). Recreating
     every tier container fixes it.
   - Step 9 never starts `ragflow-ui`: `ragflow` does not depend on it. The UI port would
     simply be gone after a deploy.

   The options are a one-off manual sequence (below) the first time, plus `ragflow-ui` added
   to step 9, or a `deploy.sh` change that does the sequence when the network differs. Not
   changed here.

### Check 1: RAGFlow has no route out

| | Result | Evidence |
|---|---|---|
| 1. Outbound from `ragflow` | pass | `curl -m 5 https://example.org` → `curl: (6) Could not resolve host`; `curl http://1.1.1.1` → `(7) Failed to connect` |
| 2. API and worker reach `ragflow:9380` | pass | `ask-spore ingest` and `sources approve --wait` on `sample-reports`: PDF 5 chunks, DOCX 1, `.md` 5, `.txt` 3, all `ingested`. The API and worker still reach the internet over `app` (HTTP 403 from example.org, a reply) |
| 3. Restart healthy, no start-up download | pass, one note | `up -d --force-recreate` of the tier: healthy after 184 s, data intact (4 documents, 14 chunks), retrieval returns 3 chunks. The only network attempt in the logs is LiteLLM's model price list (`Failed to fetch remote model cost map … falling back` to its bundled copy); harmless, and `LITELLM_LOCAL_MODEL_COST_MAP=True` would silence it. DeepDoc models (`rag/res/deepdoc`), NLTK data (`/root/nltk_data`) and bge-m3 (TEI `/data`) are in the images. No download during the four parses |
| 4. UI over the tunnel | pass (no SSH client) | No key was added to the host to open a real tunnel. Instead, on `127.0.0.1:18080`, the port a tunnel forwards to: `/` and `/dataset/dataset/<id>` 200 `text/html`; an asset 200; `/api/v1/system/healthz` 200. Through the proxy: register, sign in (session header), `users/me` and `datasets` all code 0, and the document list for a dataset showed `DONE ×4`. `tests/test_ragflow_integration.py` passes with `RAGFLOW_TEST_BASE_URL=http://127.0.0.1:18080` |
| 5. Crawled page with images | pass | Real `crawl_site` in the worker image, with the tests' `resolve`/`MockTransport` injection, against a synthetic page holding `<img>` (https, relative, `data:`), `<figure>`, `<picture>`, literal `![..](..)` and `![..][..]` text, and escaped `<img src=…>` text. Stored Markdown: no image element left; the literal syntax survives only escaped by trafilatura (`!\[literal\](…)`), which neither `IMAGE_REFERENCE` nor RAGFlow's extractor matches. Ingested (1 chunk), 0 image references in RAGFlow's chunk text, no image attempt in RAGFlow's log |

Minor, for the build: removing an escaped `<img …>` written as page text leaves a stray `\`
in the sentence. `ask-spore ingest --help` still lists "PDF, DOCX, PPTX, HTML and
Markdown", without text.

### Check 2: applying it on the live Instance (written down, not done)

Rehearsed in the scratch project from the live state (the compose file from `main`, network
not internal, RAGFlow reaching the internet with HTTP 200), then back again as the
rollback. The project is `ask-spore-dev`, and the commands run from `/root/ask.spore` after
the release is checked out. `TIER` is
`ragflow-es ragflow-mysql ragflow-minio ragflow-redis ragflow-tei ragflow`.

**Apply.**

```
C="docker compose -f infra/compose.dev.yml"
docker network disconnect ask-spore-dev_ragflow ask-spore-dev-api-1
docker network disconnect ask-spore-dev_ragflow ask-spore-dev-worker-1
$C up -d --force-recreate $TIER ragflow-ui
$C up -d --force-recreate api worker
```

- The disconnects keep the API serving sign-in, history and files. Only answers fail while
  RAGFlow restarts.
- In the rehearsal:
  - the tier command took 66 s;
  - `api` and `worker` were back at 74 s;
  - RAGFlow was healthy at 168 s;
  - `/healthz` failed for 13 of those seconds.
- Expect about 3 minutes without answers and about 15 s of API restart.
- `deploy.sh` then runs normally, if `ragflow-ui` is added to its step 9. If the release
  includes migration 0071, that is the deploy's own step and the owner's call.

**Checks after applying.**
- `curl -m 5 https://example.org` inside `ragflow` exits 6.
- `getent hosts ragflow-mysql` resolves.
- `ask-spore datasets counts` shows the same counts as before.
- `127.0.0.1:${RAGFLOW_UI_PORT}` returns 200.

**Rollback.**

```
docker rm -f ask-spore-dev-ragflow-ui-1
docker network disconnect ask-spore-dev_ragflow ask-spore-dev-api-1
docker network disconnect ask-spore-dev_ragflow ask-spore-dev-worker-1
git show <previous release>:infra/ragflow/docker-compose.yml > infra/ragflow/docker-compose.yml
$C up -d --force-recreate $TIER
$C up -d --force-recreate api worker
```

Rehearsed: RAGFlow healthy at 174 s, `/healthz` failed for 12 s, network not internal, data
intact, and the UI back on 127.0.0.1:18080, published by `ragflow` itself.

**Recovering a half-done apply.** This is the state the first scratch attempt left: tier
stopped, or the stores without aliases. Run `$C up -d --force-recreate $TIER ragflow-ui`
(with `api` and `worker` disconnected first if the network still has to be recreated), then
recreate `api worker`. Healthy at 172 s in the scratch run. All data is on named volumes;
no `down -v`.

**Documentation that still describes the old publishing:**
- `infra/compose.dev.yml` line 13 ("RAGFlow publishes only its web UI").
- The header of `infra/ragflow/docker-compose.yml`, line 7 ("except the RAGFlow web UI").
- `infra/scripts/deploy.sh` step 9 (no `ragflow-ui`).

`infra/README.md` (line 22, loopback 8080) and `infra/ragflow/README.md` (the `ssh -L`
line) stay correct: the port and the tunnel are unchanged.

### Check 3: full suites at `d07ebf2`

| Suite | Result |
|---|---|
| `ruff check .` | All checks passed! |
| `ruff format --check .` | 239 files already formatted |
| `mypy app` (`strict = true`) | Success: no issues found in 116 source files |
| `pytest` with a throwaway PostgreSQL 16.15 container, `REQUIRE_DB_TESTS=1` | 1833 passed, 2 skipped, 1 deselected. The skips are the suite's non-database conditions: the RAGFlow integration environment, which passed separately above, and a Caddy binary. The integration marker accounts for the deselected test. `test_workspace_summary.py` passes after `cf1a58f` |
| web `pnpm lint`, `pnpm typecheck` (pinned Playwright image) | pass |
| web `pnpm test` | 44 files, 230 tests passed |

No failure in any suite.
