# Eval run 20261018T005524Z-1f29494499ba

> **MOCKED RUN.** Mistral was mocked; faithfulness comes from a lexical stand-in, not a model. These numbers prove the harness, not answer quality.

> **SYNTHETIC SET.** Every item is synthetic, written against the synthetic corpus. Results say nothing about the real corpus.

- Mocked: the API ran with tests.dev_fake_mistral (Mistral mocked at the HTTP layer); RAGFlow v0.27.2 with bge-m3, Postgres and the orchestrator are real.
- Threshold experiment (P0-20): repository config with similarity_threshold 0.25 for both the API and the harness; answer cache flushed before the run.

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 100.0 |
| Retrieval hit@10 | 100.0 |
| Citation precision | 98.4 |
| Faithfulness | 43.8 |
| Abstention correctness (out_of_corpus) | 42.9 |
| Cited-answer rate (factual + synthesis) | 100.0 |

## Run

- Set: `synthetic-v0.jsonl` (38 items: 25 factual, 6 synthesis, 7 out_of_corpus), sha256 `466e049dc6a9`
- Code: `1f29494499ba`; started 2026-10-18T00:55:24+00:00, 23.6 s
- Retrieval: top_k 10, similarity threshold 0.25, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models: answer `mistral-large-2512`, rewrite `mistral-small-2603`, judge `mistral-large-2512`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `1995ab7326f93cd4`, 3 datasets

## Outcomes

- Answered 35, unsupported 0, abstained 3, errors 0
- out_of_corpus abstained without an LLM call: 42.9 points
- Retrieval step would abstain: out_of_corpus 42.9, factual + synthesis 0.0 points
- Judged statements: 34 supported, 35 unsupported, 11 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 0 in / 0 out; judge 0 in / 0 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| syn-035 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-036 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-037 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-038 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
