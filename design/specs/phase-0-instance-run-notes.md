# Phase 0 Instance run notes

Log of the coding session on the Phase 0 Instance (branch `phase-0/instance-run`, merged into `main` before power-off), Oct 18 to 19, 2026. No secrets, corpus content or real query text here. Results and decisions are in `phase-0-findings.md`; this file is how we got there, the state the Instance was left in and how to resume.

**Last update (final):** 2026-10-19 02:05 UTC. 59 of 60 documents ingested; the three threshold runs done and committed; findings sections 3, 4 and 5 written; `similarity_threshold` set to 0.25. Line 15 could not finish before the deadline and was stopped cleanly (b). Branch merged into `main`; Compose stopped; Instance powered off early by the session.

**Deadline:** the owner set a power-off at 03:50 UTC on Oct 19 (first 03:00, then extended; scheduled with `shutdown -h 03:50`). Note: a power-off from inside the OS may leave a Scaleway Instance allocated, and some resources billed, until it is stopped from the console or API. Check the console.

## (a) Done and committed

| Commit | What |
| --- | --- |
| `f2549cf` | `config/tags.toml`: DOCX → `naive`, PPTX → `presentation` under `sample-reports` (the manifest tags every file `sample-reports`) |
| `27c6f26` | `ask-spore ingest-manifest` (validate all rows first, idempotent by file hash, metadata-only summary, `--check`, `--summary`, `--crawl-dir`); log allow-list gains `manifest_line`, `count` |
| `f85c7e9`, `83147fa` | `design/specs/corpus-manifest.md` brought onto the branch, with a note that the command implements it |
| `029ddc2`, `12a1198` | `python -m eval map-sources`; `--uuid-for-shared-urls` maps files that share a canonical URL to register UUIDs |
| `54816cc` | `mistral-medium-2604` pinned (superseded by the Scaleway switch; `[mistral]` kept, inactive) |
| `883dead` | `eval run --exclude-label` |
| `9f55383`, `537198e` | RAGFlow parse tuning for CPU: `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE` (repo default 8), host-specific `cpus: ${RAGFLOW_CPUS:-0}` (findings R17) |
| `02828f7`, `8233dfc`, `bd73c8a` | Scaleway Generative APIs client (`deepseek-v4.1-flash`), `[llm] provider` switch, token-bucket throttle, findings M2 |
| `73c2606` | Eval results record the active provider's model names |
| `eb43015` | Phase 1a design addendum (CLAUDE.md, architecture §14, compliance addendum, Phase 1a spec, backlog). **Not authored by this session**: it appeared on the branch at 22:16 from another session; kept as the coordinator instructed, not reviewed here |
| `4648ede` | Merge of origin/main (Scaleway design updates, backlog item); conflicts in Stack Decision, compliance guide and backlog kept both sides |
| `b3c232e` | Findings R17 |
| `9f20637` | Eval set v1 (`packages/eval/sets/v1.jsonl`) and its README section |
| `a981e7b`, `11fba99`, `802c74c` | Eval results at thresholds 0.20, 0.25, 0.30 (with findings sections 3.5 and 4 in the first) |
| `f449b8d` | Findings sections 3 (assumptions 4 and 5) and 5, C5, cost and latency |
| `b83d6ee` | `similarity_threshold` 0.2 → 0.25 (separate commit) |

Checks on this Instance after the last code change: API ruff, format and mypy clean, 380 tests pass (database tests against a throwaway `postgres:16.15` container on `127.0.0.1:55432`, not the app database); eval package 66 pass.

## (b) Ingestion

Corpus: `/srv/corpus/Corpus/manifest.csv`, 60 rows (49 PDF, 8 DOCX, 3 PPTX), every row tagged `sample-reports`, all valid. Three `~$…pptx` Office lock files in the tree are not in the manifest and were not ingested. 1,264 PDF pages in all; two PDFs hold 692 of them (manifest lines 4 and 15: 316 and 376 pages).

**Result: 59 of 60 documents ingested** (48 PDF, 8 DOCX, 3 PPTX, 2,580 chunks, no row left `ingesting`). **Line 15 (376 pages): not ingested.** Started at 23:58 UTC as a one-row run (`/srv/ingest-out/manifest-line15.csv`, `--parse-timeout 14400`). At 02:00 it was 35 % parsed (6 of about 18 page ranges, no errors), so it needed about 6 h in all, far past the deadline. Stopped at 02:01: its RAGFlow document was deleted by ID (nothing of it is retrievable) and its row marked `failed` with the reason. RAGFlow holds exactly the 59 ingested documents.

| Run | Result |
| --- | --- |
| 1 | 2 PDFs ingested; the 316-page PDF looped on TEI timeouts (R17); stopped, document deleted, row marked failed |
| 2, 3 | Same loop with lower concurrency; stopped and cleaned the same way |
| 4 | Embedding fixed (`EMBEDDING_BATCH_SIZE=1`, `RAGFLOW_CPUS=5`), but the 316-page PDF hit the CLI's default 1,800 s `--parse-timeout`; recorded failed and removed by the ingest code |
| 5 | `--parse-timeout 7200`. Measured about 27 s of task time per PDF page; the corpus no longer fit before the deadline and line 4 would have hit 7,200 s too. Stopped at 18:26 without clean-up so RAGFlow kept parsing line 4 |
| 6 | 18:27 to 23:40 UTC, derived manifest `/srv/ingest-out/manifest-run6.csv` (the owner's rows minus lines 4 and 15, paths prefixed `Corpus/`; line mapping in `manifest-run6-lines.csv`): 56 ingested, 2 duplicate, 0 failed, 18,755 s. Summary table in `/srv/ingest-out/summary-run6.csv` |
| Line 4 | Adopted at 19:27 UTC: RAGFlow finished it `DONE` (1,128 chunks, 15 page ranges, no errors, 6,063 s); the register row was set as ingest would set it |

Each stop: the in-flight RAGFlow document was deleted by ID and its `sources` row set to `failed` with the reason. The 5 `failed` PDF rows in the register are that history; re-running the manifest creates a new row for a file. At 17:55 the session's own container restarted; the Instance did not reboot and the ingestion container kept running.

Measurements (findings section 3 item 5): memory peak 17.7 GiB for all containers (host 18.0 of 31 GiB); PDFs 26.6 s of task time per page, two tasks in parallel; embedding 15 % of parse time. Spot-check findings: findings section 4 (web pages printed to PDF dominate the PDFs and parse badly; glued words; DOCX paragraphs run together; PPTX good).

## (c) Eval

- **Set v1:** `packages/eval/sets/v1.jsonl`, 60 items (30 factual, 20 synthesis, 10 out_of_corpus) converted from the owner's `/eval-v1-source/spore_eval_v1.jsonl`. Aliases, the two `pending-source` items and the 28 UUID items are listed in `packages/eval/README.md`.
- **Runs (all committed under `packages/eval/results/`):** threshold 0.20 `20261018T234144Z-9f20637f0c6f`, 0.25 `20261018T234701Z-a981e7bd8911`, 0.30 `20261018T235229Z-11fba9927728`. 58 items each (`hc-v1-029`, `hc-v1-049` excluded), on 59 of 60 documents (line 15 missing; no v1 item names it).
- **Headline:** hit@5 = hit@10 = 100 at 0.20 and 0.25; citation precision 79 to 89; faithfulness 78 to 81; abstention correctness only 10 to 30 (the model answers near-miss questions); latency median 2.05 s, p95 6.4 s. Threshold set to 0.25 by the pre-registered rule. Details and recommendations: findings section 5.
- **Not done:** a re-run with line 15 ingested; runs at `top_k` 8 or threshold 0.28 (proposed in section 5); the prompt v2 for abstention.

## (d) Issues found and how they ended

| Issue | Resolution |
| --- | --- |
| Mistral: Large not on the account's tier (403); Medium and Small refused with a zero request quota (429, limit 0) | Owner switched Phase 0 to Scaleway `deepseek-v4.1-flash` (findings M2). Mistral config kept, inactive |
| Scaleway compliance controls | **Open**: DPA, written ZDR confirmation, EU region pin and treatment of provider-side prompt caching (usage reports `cached_tokens`) are not on file. Team-written eval questions on public documents only; no real user queries until closed |
| DeepSeek reasons by default | `reasoning_effort = "none"` (0 reasoning tokens) |
| RAGFlow embedding timeouts on long PDFs (OCR saturates the CPU, TEI misses RAGFlow's hard-coded 30 s timeout) | `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE=1`, `RAGFLOW_CPUS=5` on this Instance (findings R17) |
| CPU: AMD EPYC 7401P (Zen 1, AVX2 only), Scaleway `GP1-S`, fr-par-1 | Resize before Phase 1 (findings section 3 item 5) |
| CLI default `--parse-timeout` 1,800 s too short for long PDFs on this host | Use at least 30 s per page |
| Shared canonical URLs (7 URLs, 21 rows) would inflate eval metrics | Register UUIDs for those files in v1 (option a); owner asked for distinct document URLs (option b) |
| Corpus deviations from the build spec | No crawled sites (spec: 2); no own DOCX/PPTX analysis (spec: 10); all files third-party under one tag |
| Intermittent 404 on posting to a just-created conversation (commit after the response) | **Open**, findings C5, proposed fix there; one eval item errored once |
| Orchestrator de-duplicates only within a source; identical text from two files fills two slots | Open, findings section 4 |
| Harness recorded `[mistral]` model names whatever the provider | Fixed in `73c2606` before any real run |
| GitHub push from the Instance | Fixed by the owner (credential helper) |
| pnpm, Node not installed | Not needed for this task; web checks not run here |
| Security: the session ran `docker compose config`, which printed the resolved environment; the value of `MISTRAL_API_KEY` appeared in the session's tool output (not in any file, log or commit) | **Owner: revoke that Mistral key.** Only specific fields were inspected afterwards |

## (e) State of the Instance at shutdown

- `/srv/corpus/Corpus/`: the corpus and `manifest.csv` (owner's files, unchanged; read-only to the containers).
- `/eval-v1-source/spore_eval_v1.jsonl`: the owner's eval set source.
- `/srv/ingest-out/`: derived manifests (`manifest-run6.csv`, `manifest-run6-lines.csv`, `manifest-line15.csv`) and the summary table `summary-run6.csv`; no titles or content.
- Root `.env` keys (names only): `MISTRAL_API_KEY`, `SCALEWAY_API_KEY`, `SCALEWAY_PROJECT_ID`, `PHASE0_BEARER_TOKEN`, `RAGFLOW_API_KEY`, `PHASE0_INTERNAL_USERS`, `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `REDIS_URL`.
- `infra/ragflow/.env` differs from `.env.example` in: the four passwords, `REGISTER_ENABLED=0`, `RAGFLOW_CPUS=5`, `EMBEDDING_BATCH_SIZE=1`.
- RAGFlow: one registered account (registration closed); datasets `ask-spore-sample-reports` (all documents), `ask-spore-sample-analysis`, `ask-spore-sample-web` (empty).
- Postgres `askspore`: `sources` (59 `ingested`, 6 `failed` history rows, 1 `withdrawn` synthetic dry-run row), `datasets` mapping; eval conversations were deleted after each item.
- Docker volumes: `ask-spore-dev_postgres_data`, `_ragflow_esdata`, `_ragflow_mysql`, `_ragflow_minio`, `_ragflow_redis`, `_ragflow_logs`. Compose stopped cleanly before power-off.
- The API runs the repository config (`similarity_threshold` 0.25). The throwaway test database container `askspore-testpg` was removed.

## (f) How to resume

```
cd /root/ask.spore && git checkout main && git pull
docker compose -f infra/compose.dev.yml up -d
docker compose -f infra/compose.dev.yml ps        # wait until ragflow and api are healthy
# finish anything incomplete; ingested files report duplicate
docker compose -f infra/compose.dev.yml run --rm -v /srv/corpus/Corpus:/corpus:ro -v /srv/ingest-out:/out \
  api ask-spore ingest-manifest /corpus/manifest.csv --summary /out/summary.csv --parse-timeout 28800
```

**First thing to do: line 15 is not ingested.** The command above ingests it (about 6 h on this Instance, hence the 8 h timeout; everything else reports `duplicate`). Better: do it after resizing (findings section 3 item 5). Then re-run the eval (no v1 item names line 15, but its chunks change what retrieval returns for other items):

```
set -a; . ./.env; set +a; export EVAL_USER_EMAIL="${PHASE0_INTERNAL_USERS%%:*}"
docker compose -f infra/compose.dev.yml exec -T redis redis-cli FLUSHDB
uv run --directory packages/eval python -m eval run --config ../../config/models.toml --set sets/v1.jsonl \
  --api-url http://127.0.0.1:8000 --ragflow-url http://127.0.0.1:8080 --exclude-label pending-source
```

For a threshold or `top_k` experiment, change `[chat]` for both the API and the harness (a copy of `config/` passed with `--config`, mounted into the API at `/srv/config`), restart the API and flush Redis before the run, as `packages/eval/README.md` says.

## (g) Next steps, in order, and owner decisions

1. **Owner:** revoke the exposed `MISTRAL_API_KEY`.
2. **Owner:** Scaleway DPA, written ZDR confirmation, region and prompt-caching terms before any real user query (M2).
3. **Owner:** Brookdale 2022 vs 2023 for `hc-v1-029`, `hc-v1-049`.
4. **Owner:** distinct document URLs for the 21 shared-URL rows (then re-run `map-sources`; the UUIDs disappear).
5. **Owner:** re-capture the web pages printed to PDF by crawling them (findings section 4), and add the 2 crawled sites and own DOCX/PPTX analysis the spec asks for.
6. **Owner:** resize or move ingestion before Phase 1 (findings section 3 item 5).
7. Fix C5 (conversation commit before the response), with a test.
8. Prompt `corpus_only/v2` for abstention on near misses, and more out-of-corpus items in set v2; then eval runs at `top_k` 8 and threshold 0.28.
9. Content editor: the side-by-side parsing review in the RAGFlow UI (checklist section 3).
