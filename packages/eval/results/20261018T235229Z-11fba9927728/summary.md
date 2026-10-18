# Eval run 20261018T235229Z-11fba9927728

- Real run: Scaleway deepseek-v4.1-flash (answers, rewrite, judge), RAGFlow v0.27.2 bge-m3, real corpus.
- Threshold experiment: similarity_threshold 0.30 for both the API and the harness; answer cache flushed before the run.
- Corpus: 59 of 60 documents (manifest line 15, a 376-page PDF, not ingested; no v1 item names it). Items hc-v1-029 and hc-v1-049 excluded (pending-source).

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 85.4 |
| Retrieval hit@10 | 85.4 |
| Citation precision | 89.2 |
| Faithfulness | 77.9 |
| Abstention correctness (out_of_corpus) | 30.0 |
| Cited-answer rate (factual + synthesis) | 85.4 |

## Run

- Set: `v1.jsonl` (58 items: 29 factual, 19 synthesis, 10 out_of_corpus), sha256 `ac3ca1ec42c6`
- Excluded by label pending-source: `hc-v1-029`, `hc-v1-049`
- Code: `11fba9927728`; started 2026-10-18T23:52:29+00:00, 158.3 s
- Retrieval: top_k 10, similarity threshold 0.3, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models (scaleway): answer `deepseek-v4.1-flash`, rewrite `deepseek-v4.1-flash`, judge `deepseek-v4.1-flash`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `781336a85136b182`, 3 datasets

## Outcomes

- Answered 48, unsupported 0, abstained 10, errors 0
- out_of_corpus abstained without an LLM call: 30.0 points
- Retrieval step would abstain: out_of_corpus 30.0, factual + synthesis 14.6 points
- Judged statements: 184 supported, 86 unsupported, 134 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 152557 in / 10644 out; judge 80186 in / 6038 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| hc-v1-032 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-038 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-039 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-042 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-045 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-048 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-050 | synthesis | abstained | no | no expected source in the top 10 |
| hc-v1-051 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-055 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-056 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-057 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-058 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-059 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-060 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
