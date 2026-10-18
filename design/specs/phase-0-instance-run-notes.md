# Phase 0 Instance run notes

Living log of the coding session on the Phase 0 Instance (branch `phase-0/instance-run`), Oct 18, 2026. Updated at every milestone and at least hourly; the last pushed version is the state of record if the Instance powers off mid-work. No secrets, corpus content or real query text here.

**Last update:** 2026-10-18 17:50 UTC: ingestion run 5 in progress; eval not started.

**Deadline:** the owner set a power-off at 03:00 UTC on Oct 19 (`shutdown -h 03:00` is scheduled on the Instance; cancel with `shutdown -c`). Note: a power-off from inside the OS may leave a Scaleway Instance allocated (and billed for some resources) until it is stopped from the console or API; check the console.

## (a) Done and committed

| Commit | What |
| --- | --- |
| `f2549cf` | `config/tags.toml`: DOCX → `naive`, PPTX → `presentation` under `sample-reports` (the manifest tags every file `sample-reports`) |
| `27c6f26` | `ask-spore ingest-manifest` (validate all rows first, idempotent by file hash, metadata-only summary, `--check`, `--summary`, `--crawl-dir`); log allow-list gains `manifest_line`, `count` |
| `f85c7e9`, `83147fa` | `design/specs/corpus-manifest.md` brought onto the branch, with a note that the command implements it |
| `029ddc2`, `12a1198` | `python -m eval map-sources`: file-name sources to canonical URLs; `--uuid-for-shared-urls` maps files that share a canonical URL to register UUIDs |
| `54816cc` | `mistral-medium-2604` pinned (superseded by the Scaleway switch; `[mistral]` kept, inactive) |
| `883dead` | `eval run --exclude-label` |
| `9f55383`, `537198e` | RAGFlow parse tuning for CPU: `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE` (repo default 8), host-specific `cpus: ${RAGFLOW_CPUS:-0}` |
| `02828f7`, `8233dfc`, `bd73c8a` | Scaleway Generative APIs client (`deepseek-v4.1-flash`), `[llm] provider` switch, token-bucket throttle, findings M2 |

Checks on this Instance: API ruff, format and mypy clean, 380 tests pass (database tests against a throwaway `postgres:16.15` container on `127.0.0.1:55432`, not the app database); eval package 65 pass.

## (b) Ingestion

Corpus: `/srv/corpus/Corpus/manifest.csv`, 60 rows (49 PDF, 8 DOCX, 3 PPTX), every row tagged `sample-reports`, all valid. Three `~$…pptx` Office lock files in the tree are not in the manifest and are not ingested. 1,264 PDF pages in all; two PDFs hold 692 of them (manifest lines 4 and 15: 316 and 376 pages).

Runs (logs in the session scratchpad, not kept):

| Run | Result |
| --- | --- |
| 1 | 2 PDFs ingested; the 316-page PDF looped on TEI timeouts (R17); stopped, document deleted, row marked failed |
| 2, 3 | Same loop with lower concurrency; stopped and cleaned the same way |
| 4 | Embedding fixed (`EMBEDDING_BATCH_SIZE=1`, `RAGFLOW_CPUS=5`), but the 316-page PDF hit the CLI's default 1,800 s `--parse-timeout`; recorded failed and removed by the ingest code |
| 5 | In progress, `--parse-timeout 7200` |

Each stop: the in-flight RAGFlow document was deleted by ID and its `sources` row set to `failed` with the reason. Failed rows stay as history; re-running the manifest creates a new row for the file. Expected end of run 5: about 22:00 UTC (about 12 s per PDF page).

Parse spot checks (first PDFs): HTML tables kept with header rows; words glued in display headings and table labels (7 to 11 per document); multi-column and infographic pages come out as short fragmented lines; recurring section labels repeat across chunks. Full results go in findings section 4.

## (c) Eval

- Set v1 source: `/eval-v1-source/spore_eval_v1.jsonl` (60 items: 30 factual, 20 synthesis, 10 out_of_corpus), confirmed by the owner. Sources are named by file name; `map-sources` converts them.
- Aliases applied (same documents, different names): Elior (`[GPO]` → `[FSMC]` prefix), Gundersen (spelling), AdventHealth climate resilience plan (renamed).
- Pending: `hc-v1-029`, `hc-v1-049` name a 2022 Brookdale report; the corpus has only the 2023 one. Plan: map provisionally to the 2023 report, label `pending-source`, run with `--exclude-label pending-source`.
- 28 items reference files whose canonical URL is shared with other files (21 manifest rows, 7 landing-page URLs); after ingestion they get register UUIDs (`--uuid-for-shared-urls`). They must be re-mapped if those sources are re-ingested.
- Threshold runs (0.20, 0.25, 0.30): not started. Smoke test passed (one factual item, answered with 2 correct citations, 3.8 s, 4,834 tokens in, 65 out).

## (d) Issues found today

| Issue | Resolution |
| --- | --- |
| Mistral: Large not on the account's tier (403); Medium and Small refused with a zero request quota (429, limit 0) | Owner switched Phase 0 to Scaleway `deepseek-v4.1-flash` (findings M2). Mistral config kept, inactive |
| Scaleway compliance controls | **Open**: DPA, written ZDR confirmation, EU region pin and treatment of provider-side prompt caching (usage reports `cached_tokens`) are not on file. Team-written eval questions on public documents only; no real user queries until closed |
| DeepSeek reasons by default | `reasoning_effort = "none"` (0 reasoning tokens) |
| RAGFlow embedding timeouts on long PDFs: OCR saturates the CPU, TEI misses RAGFlow's hard-coded 30 s timeout | `MAX_CONCURRENT_TASKS=2`, `EMBEDDING_BATCH_SIZE=1` and `RAGFLOW_CPUS=5` on this Instance (findings R17) |
| CPU: AMD EPYC 7401P (Zen 1, AVX2, no AVX-512), Scaleway `GP1-S`, fr-par-1; bge-m3 on TEI at about 65 to 100 tokens/s | Resize recommendation in findings section 3 item 5 |
| CLI default `--parse-timeout` 1,800 s too short for 300+ page PDFs on this host | Run 5 uses 7,200 s |
| Shared canonical URLs (7 URLs, 21 rows) inflate eval metrics | UUIDs for those files (option a); owner asked for distinct document URLs (option b) |
| Corpus deviations from the build spec | No crawled sites (spec: 2); no own DOCX/PPTX analysis (spec: 10); all files third-party under one tag |
| GitHub push from the Instance | Fixed by the owner (credential helper) |
| pnpm, Node not installed | Not needed for this task; web checks not run here |

## (e) State of the Instance

- `/srv/corpus/Corpus/`: the corpus and `manifest.csv` (owner's files, read-only to the containers).
- `/eval-v1-source/spore_eval_v1.jsonl`: the owner's eval set source.
- `/srv/ingest-out/summary.csv`: ingest summary table (line, type, status, chunks, seconds, source IDs; no titles).
- Root `.env` keys: `MISTRAL_API_KEY`, `SCALEWAY_API_KEY`, `SCALEWAY_PROJECT_ID`, `PHASE0_BEARER_TOKEN`, `RAGFLOW_API_KEY`, `PHASE0_INTERNAL_USERS`, `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `REDIS_URL`.
- `infra/ragflow/.env` differs from `.env.example` in: the four passwords, `REGISTER_ENABLED=0`, `RAGFLOW_CPUS=5`, `EMBEDDING_BATCH_SIZE=1`.
- RAGFlow: one registered account (registration closed); datasets `ask-spore-sample-reports`, `ask-spore-sample-analysis`, `ask-spore-sample-web` (only the first holds documents).
- Postgres `askspore`: `sources` rows (ingested, failed history, one withdrawn synthetic dry-run row), `datasets` mapping, eval conversations are deleted after each item.
- Docker volumes: `ask-spore-dev_postgres_data`, `_ragflow_esdata`, `_ragflow_mysql`, `_ragflow_minio`, `_ragflow_redis`, `_ragflow_logs`.
- Throwaway test database container `askspore-testpg` (not part of Compose; safe to remove).

## (f) How to resume

```
cd /root/ask.spore && git pull
docker compose -f infra/compose.dev.yml up -d
# wait until ragflow and api report healthy
docker compose -f infra/compose.dev.yml ps
# finish anything incomplete (idempotent: ingested files report duplicate)
docker compose -f infra/compose.dev.yml run --rm -v /srv/corpus/Corpus:/corpus:ro -v /srv/ingest-out:/out \
  api ask-spore ingest-manifest /corpus/manifest.csv --summary /out/summary.csv --parse-timeout 7200
```

Then the eval set and runs (commands in `packages/eval/README.md`; set `[chat] similarity_threshold`, restart the API and flush Redis before each run).

## (g) Next steps and owner decisions

1. Finish ingestion; spot-check parsing; findings section 4 and section 3 item 5.
2. Eval set v1 commit; threshold runs 0.20, 0.25, 0.30; findings sections 3 item 4 and 5; cost and latency.
3. Owner: Brookdale 2022 vs 2023 (`hc-v1-029`, `hc-v1-049`).
4. Owner: distinct document URLs for the 21 shared-URL rows.
5. Owner: Scaleway DPA, ZDR, region and prompt-caching confirmation before any real user query.
6. Owner: resize or move embedding before Phase 1 (section 3 item 5).
