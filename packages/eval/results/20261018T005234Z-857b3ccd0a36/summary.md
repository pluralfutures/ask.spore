# Eval run 20261018T005234Z-857b3ccd0a36

> **MOCKED RUN.** Mistral was mocked; faithfulness comes from a lexical stand-in, not a model. These numbers prove the harness, not answer quality.

> **SYNTHETIC SET.** Every item is synthetic, written against the synthetic corpus. Results say nothing about the real corpus.

- Mocked: the API ran with tests.dev_fake_mistral (Mistral mocked at the HTTP layer); RAGFlow v0.27.2 with bge-m3, Postgres and the orchestrator are real.
- Baseline: repository config (similarity_threshold 0.2); synthetic corpus ingested with fixtures/corpus/ingest.sh.

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 100.0 |
| Retrieval hit@10 | 100.0 |
| Citation precision | 88.7 |
| Faithfulness | 46.8 |
| Abstention correctness (out_of_corpus) | 28.6 |
| Cited-answer rate (factual + synthesis) | 100.0 |

## Run

- Set: `synthetic-v0.jsonl` (38 items: 25 factual, 6 synthesis, 7 out_of_corpus), sha256 `466e049dc6a9`
- Code: `857b3ccd0a36`; started 2026-10-18T00:52:34+00:00, 24.0 s
- Retrieval: top_k 10, similarity threshold 0.2, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models: answer `mistral-large-2512`, rewrite `mistral-small-2603`, judge `mistral-large-2512`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `1995ab7326f93cd4`, 3 datasets

## Outcomes

- Answered 36, unsupported 0, abstained 2, errors 0
- out_of_corpus abstained without an LLM call: 28.6 points
- Retrieval step would abstain: out_of_corpus 28.6, factual + synthesis 0.0 points
- Judged statements: 39 supported, 36 unsupported, 15 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 0 in / 0 out; judge 0 in / 0 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| syn-032 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-035 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-036 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-037 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| syn-038 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
