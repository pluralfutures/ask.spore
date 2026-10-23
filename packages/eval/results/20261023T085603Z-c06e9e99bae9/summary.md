# Eval run 20261023T085603Z-c06e9e99bae9

- P1b-16 release step 7.4: vector_similarity_weight 0.4, main c06e9e9, temporary askspore-eval-api

| Metric | Points |
| --- | ---: |
| Retrieval hit@5 | 98.0 |
| Retrieval hit@10 | 100.0 |
| Citation precision | 82.8 |
| Faithfulness | 90.8 |
| Abstention correctness (out_of_corpus) | 80.0 |
| Cited-answer rate (factual + synthesis) | 98.0 |

## Run

- Set: `v1.jsonl` (60 items: 30 factual, 20 synthesis, 10 out_of_corpus), sha256 `ac3ca1ec42c6`
- Code: `c06e9e99bae9` (uncommitted changes); started 2026-10-23T08:56:03+00:00, 417.7 s
- Retrieval: top_k 10, similarity threshold 0.25, vector weight 0.4, max context tokens 6000, embedding `BAAI/bge-m3@Builtin`, RAGFlow v0.27.2
- Models (scaleway): answer `deepseek-v4.1-flash`, rewrite `deepseek-v4.1-flash`, judge `qwen3.8-27b` (scaleway); prompts corpus_only/v5, rewrite/v1, judge/v1
- Corpus version `7a48140b45c8bd23`, 3 datasets

## Outcomes

- Answered 51, unsupported 9, abstained 0, errors 0
- out_of_corpus abstained without an LLM call: 0.0 points
- Retrieval step would abstain: out_of_corpus 0.0, factual + synthesis 0.0 points
- Judged statements: 346 supported, 51 unsupported, 206 no claim; judge errors 0, excerpt fallbacks 0
- Tokens: pipeline 343830 in / 18683 out; judge 148075 in / 8723 out

## Warnings

- Run from a working tree with uncommitted changes.

## Items to look at

| Item | Type | Outcome | hit@10 | Note |
| --- | --- | --- | --- | --- |
| hc-v1-055 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
| hc-v1-058 | out_of_corpus | answered | n/a | answered an out_of_corpus question |
