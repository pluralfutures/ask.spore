# packages/eval

Evaluation set and harness (P0-17, P0-18).

| Path | What |
| --- | --- |
| `sets/` | Eval sets, one JSON object per line (`.jsonl`). `template.jsonl` shows one item of each type. |
| `sets/synthetic-v0.jsonl` | **Synthetic** set (38 invented items) against the synthetic corpus, used to prove the harness end to end. Not eval set v1. |
| `schema/eval-item.schema.json` | JSON Schema of one item, generated from `eval/schema.py` (`python -m eval schema --write`). |
| `fixtures/corpus/` | Synthetic corpus (invented organisations and figures) and `ingest.sh`, which ingests it with the canonical URLs the synthetic set expects. |
| `results/` | Harness output, one folder per run: `results.json` and `summary.md`. |
| `eval/` | Schema and validator (`schema.py`), harness (`runner.py`, `retrieval.py`, `pipeline.py`, `judge.py`, `metrics.py`), `compare`. |

Commands, from the repository root:

```
uv run --directory packages/eval python -m eval validate sets/v1.jsonl
uv run --directory packages/eval python -m eval validate sets/synthetic-v0.jsonl --min-items 30 --min-out-of-corpus 6
```

`validate` checks every line and lists every problem with its line number. By default it also
requires the spec's minimums for eval set v1: at least 60 items, at least 10 of them
`out_of_corpus`.

## Running the harness (P0-18)

```
uv run --directory packages/eval python -m eval run --config ../../config/models.toml \
    --set sets/v1.jsonl --api-url http://<api-host>:8000
uv run --directory packages/eval python -m eval compare results/<base> results/<new>
```

For every item, `run`:

1. **Retrieval step.** Runs the orchestrator's retrieval step on its own, with the same building
   blocks and `[chat]` parameters (`app.chat.package`, `app.retrieval.ragflow`,
   `app.chat.context.select_context`): records the ranked chunks' sources and scores, hit@5 and
   hit@10, and whether the orchestrator would abstain (nothing left after threshold,
   de-duplication and the token cap).
2. **Full pipeline.** Asks the question through the API under test as the first message of a new
   conversation (`POST /api/v1/conversations/{id}/messages`, the SSE stream), then deletes the
   conversation. Records the outcome (answered, unsupported, abstained, error), the answer, the
   citations and citation precision.
3. **Judge.** For an answer the model produced, splits it into sentences and asks the judge
   (Mistral Large on the EU endpoint, through `app.llm.mistral.MistralClient.judge`, prompt
   `config/prompts/judge/v1.md`) whether each sentence is supported by the passages it cites.

Metrics, all in points where higher is better: retrieval hit@5 and hit@10, citation precision,
faithfulness, abstention correctness (out_of_corpus items answered without any citation), and the
cited-answer rate on factual and synthesis items (the cost side of abstention). Definitions are in
`eval/metrics.py`. `compare` exits 1 when any of them drops by more than `--threshold` points
(default 3).

Environment: `MISTRAL_API_KEY` (judge), `RAGFLOW_API_KEY` and `DATABASE_URL` (retrieval step;
the database is only read), `PHASE0_BEARER_TOKEN` and `EVAL_USER_EMAIL` (a seeded internal user,
for the API). `--ragflow-url` (or `EVAL_RAGFLOW_URL`) points the retrieval step at RAGFlow when
`ragflow.base_url` does not resolve where the harness runs; it must be a private or loopback
address. The harness and the API under test must run the same `config/` (the harness records its
own configuration in the results; the API does not report its own).

Results go to `results/<UTC timestamp>-<git sha>/`. They hold answers and judged sentences but no
chunk text. Answers served from the API's answer cache are counted and flagged: the cache key
does not include retrieval parameters (findings), so flush the cache after changing them.

### In GitHub Actions (P0-19)

`.github/workflows/eval.yml` is triggered by hand (Actions → Eval → Run workflow). Inputs: the
API URL, the RAGFlow URL for the retrieval step, the eval set, the runner label, an optional item
limit, and an optional baseline folder under `results/` to `compare` against (the job fails on a
regression). Secrets, read only when it runs: `MISTRAL_API_KEY`, `RAGFLOW_API_KEY`,
`EVAL_DATABASE_URL`, `PHASE0_BEARER_TOKEN`, `EVAL_USER_EMAIL`, and `EVAL_API_URL` /
`EVAL_RAGFLOW_URL` if the inputs are left empty. A missing secret fails the first step by name.

The runner must reach the target's API, RAGFlow and Postgres. RAGFlow and Postgres have no public
listener (CLAUDE.md), so against the Phase 0 Instance use a self-hosted runner on the Instance's
private network and pass its label; a GitHub-hosted runner can reach only a target that is public.
The results folder is uploaded as the artifact `eval-results-<run id>`; to keep a run, download it
and commit it under `results/`.

### Without a Mistral key (dev only)

Run the API with Mistral mocked at the HTTP layer and give the harness `--mock-mistral`, which
replaces the judge's transport with a lexical stand-in (`eval/mock.py`). The run is labelled
**MOCKED** in its summary and in `compare`.

```
uv run --directory apps/api python -m tests.dev_fake_mistral --port 8001
uv run --directory packages/eval python -m eval run --set sets/synthetic-v0.jsonl \
    --api-url http://127.0.0.1:8001 --mock-mistral --note "API: tests.dev_fake_mistral"
```

## Writing eval set v1 (research team)

Eval set v1 is `sets/v1.jsonl`, written by the research team from the **real** sample corpus
ingested on the Phase 0 Instance. The harness does not depend on the synthetic set; it runs
whatever set it is given.

### One item

```json
{"id": "v1-001", "question": "What was installed offshore wind capacity in the Tidewater region at the end of 2025?", "type": "factual", "expected_source_ids": ["https://publisher.example/reports/tidewater-2026"], "expected_answer_notes": "4.2 GW at the end of 2025 (Table 1).", "labels": ["pdf", "table"]}
```

Each item is one line. Start from `sets/template.jsonl`.

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable identifier, unique in the set: letters, digits, `.`, `_`, `-`, up to 64 characters. Results are compared by `id`, so never reuse an `id` for a different question; retire it and add a new one. |
| `question` | yes | Asked exactly as written, as the first message of a new conversation (no follow-ups in v1). At most 4,000 characters. |
| `type` | yes | `factual`: one fact from one source. `synthesis`: combines several statements, usually from several sources. `out_of_corpus`: the corpus cannot answer it. |
| `expected_source_ids` | yes | The sources that answer the question. Each entry is either the source's **canonical URL** exactly as registered at ingestion (`--canonical-url`) or its **source register UUID** (`sources.id`). At least one for `factual` and `synthesis`; must be `[]` for `out_of_corpus`. |
| `expected_answer_notes` | yes | What a correct answer says (figures, units, years, the gist), for whoever reviews the results. For `out_of_corpus`, why the corpus cannot answer. Not sent to any model. |
| `labels` | no | Free grouping for review, lowercase: e.g. `pdf`, `table`, `speaker-notes`, `lang:de`, `near-miss`. |
| `synthetic` | no | `true` only for invented items. Leave it out in v1. |

### Rules of thumb

- **At least 60 items, at least 10 `out_of_corpus`.** Aim for a mix by source type (PDF, DOCX, PPTX, crawled pages) and by where the answer sits (body text, tables, slides, figure captions).
- **Prefer canonical URLs** in `expected_source_ids`: they survive re-ingestion, while a source's UUID changes if it is deleted and ingested again. Use the UUID for own DOCX/PPTX analysis registered without a canonical URL. The harness warns about entries that match no source in the register.
- **List every source that fully answers the question**, not only the one you had in mind. A source that is cited but not listed lowers citation precision.
- **`out_of_corpus` items** should include *near misses*, not only off-topic questions: a year, region or technology next to what the corpus covers ("onshore" when the corpus has only offshore). Off-topic questions test the similarity threshold; near misses test the model's refusal.
- **Write questions the way an analyst would ask them**, not copied from a sentence in the source: copied wording inflates retrieval scores.
- **No client data, no real user queries, no personal data.** Questions are written by the research team from the corpus.
- **Changing a question** means a new `id`. Do not edit a released item in place.
- Run `validate` before committing; CI runs it too.

## Synthetic set

`sets/synthetic-v0.jsonl` exists so that the harness can be run and tested before v1 exists. Its
items are invented, marked `"synthetic": true`, use ids `syn-NNN`, and point at
`https://example.org/synthetic/...` canonical URLs set by `fixtures/corpus/ingest.sh`. Results
from it say nothing about the real corpus.

```
uv run --directory apps/api ask-spore datasets sync
sh packages/eval/fixtures/corpus/ingest.sh
```
