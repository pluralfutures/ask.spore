# Eval run 20261018T005642Z-1f29494499ba

> **MOCKED RUN.** Mistral was mocked; faithfulness comes from a lexical stand-in, not a model. These numbers prove the harness, not answer quality.

> **SYNTHETIC SET.** Every item is synthetic, written against the synthetic corpus. Results say nothing about the real corpus.

- Mocked: the API ran with tests.dev_fake_mistral (Mistral mocked at the HTTP layer); RAGFlow v0.27.2 with bge-m3, Postgres and the orchestrator are real.
- Threshold experiment (P0-20): repository config with similarity_threshold 0.3 for both the API and the harness; answer cache flushed before the run.

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 90.3 |
| Retrieval hit@10 | 90.3 |
| Citation precision | 100.0 |
| Faithfulness | 41.4 |
| Abstention correctness (out_of_corpus) | 57.1 |
| Cited-answer rate (factual + synthesis) | 90.3 |

## Run

- Set: `synthetic-v0.jsonl` (38 items: 25 factual, 6 synthesis, 7 out_of_corpus), sha256 `466e049dc6a9`
- Code: `1f29494499ba`; started 2026-10-18T00:56:42+00:00, 24.5 s
- Retrieval: top_k 10, similarity threshold 0.3, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models: answer `mistral-large-2512`, rewrite `mistral-small-2603`, judge `mistral-large-2512`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `1995ab7326f93cd4`, 3 datasets

## Outcomes

- Answered 31, unsupported 0, abstained 7, errors 0
- out_of_corpus abstained without an LLM call: 57.1 points
- Retrieval step would abstain: out_of_corpus 57.1, factual + synthesis 9.7 points
- Judged statements: 29 supported, 31 unsupported, 5 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 0 in / 0 out; judge 0 in / 0 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| syn-010 | factual | abstained | no | no expected source in the top 10 |
| syn-026 | synthesis | abstained | no | no expected source in the top 10 |
| syn-029 | synthesis | abstained | no | no expected source in the top 10 |
| syn-036 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-037 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-038 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
