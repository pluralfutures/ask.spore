# Eval run 20261018T234701Z-a981e7bd8911

- Real run: Scaleway deepseek-v4.1-flash (answers, rewrite, judge), RAGFlow v0.27.2 bge-m3, real corpus.
- Threshold experiment: similarity_threshold 0.25 for both the API and the harness; answer cache flushed before the run.
- Corpus: 59 of 60 documents (manifest line 15, a 376-page PDF, not ingested; no v1 item names it). Items hc-v1-029 and hc-v1-049 excluded (pending-source).

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 100.0 |
| Retrieval hit@10 | 100.0 |
| Citation precision | 83.5 |
| Faithfulness | 80.9 |
| Abstention correctness (out_of_corpus) | 10.0 |
| Cited-answer rate (factual + synthesis) | 100.0 |

## Run

- Set: `v1.jsonl` (58 items: 29 factual, 19 synthesis, 10 out_of_corpus), sha256 `ac3ca1ec42c6`
- Excluded by label pending-source: `hc-v1-029`, `hc-v1-049`
- Code: `a981e7bd8911`; started 2026-10-18T23:47:01+00:00, 244.6 s
- Retrieval: top_k 10, similarity threshold 0.25, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models (scaleway): answer `deepseek-v4.1-flash`, rewrite `deepseek-v4.1-flash`, judge `deepseek-v4.1-flash`; prompts corpus_only/v1, rewrite/v1, judge/v1
- Corpus version `781336a85136b182`, 3 datasets

## Outcomes

- Answered 56, unsupported 1, abstained 0, errors 1
- out_of_corpus abstained without an LLM call: 0.0 points
- Retrieval step would abstain: out_of_corpus 0.0, factual + synthesis 0.0 points
- Judged statements: 292 supported, 115 unsupported, 208 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 303285 in / 17535 out; judge 155235 in / 9039 out

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| hc-v1-024 | factual | error | yes | http_404 |
| hc-v1-051 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-052 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-053 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-054 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-055 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-057 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-058 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-059 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-060 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
