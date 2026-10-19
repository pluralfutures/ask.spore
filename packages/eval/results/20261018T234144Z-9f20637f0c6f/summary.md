# Eval run 20261018T234144Z-9f20637f0c6f

- Real run: Scaleway deepseek-v4.1-flash (answers, rewrite, judge), RAGFlow v0.27.2 bge-m3, real corpus.
- Threshold experiment: similarity_threshold 0.20 for both the API and the harness; answer cache flushed before the run.
- Corpus: 59 of 60 documents (manifest line 15, a 376-page PDF, not ingested; no v1 item names it). Items hc-v1-029 and hc-v1-049 excluded (pending-source).

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 100.0 |
| Retrieval hit@10 | 100.0 |
| Citation precision | 79.2 |
| Faithfulness | 79.0 |
| Abstention correctness (out_of_corpus) | 30.0 |
| Cited-answer rate (factual + synthesis) | 100.0 |

## Run

- Set: `v1.jsonl` (58 items: 29 factual, 19 synthesis, 10 out_of_corpus), sha256 `ac3ca1ec42c6`
- Excluded by label pending-source: `hc-v1-029`, `hc-v1-049`
- Code: `9f20637f0c6f`; started 2026-10-18T23:41:44+00:00, 244.1 s
- Retrieval: top_k 10, similarity threshold 0.2, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models (scaleway): answer `deepseek-v4.1-flash`, rewrite `deepseek-v4.1-flash`, judge `deepseek-v4.1-flash`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `781336a85136b182`, 3 datasets

## Outcomes

- Answered 55, unsupported 3, abstained 0, errors 0
- out_of_corpus abstained without an LLM call: 0.0 points
- Retrieval step would abstain: out_of_corpus 0.0, factual + synthesis 0.0 points
- Judged statements: 296 supported, 114 unsupported, 222 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 309844 in / 17497 out; judge 145097 in / 9296 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| hc-v1-051 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-054 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-055 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-057 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-058 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-059 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-060 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
