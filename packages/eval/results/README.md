# Eval results

One folder per harness run, `<UTC timestamp>-<git sha>/`, holding `results.json` (configuration,
metrics, per-item records) and `summary.md`. Never edit a run; compare two with
`python -m eval compare <base> <new>`.

| Run | Set | What |
| --- | --- | --- |
| `20261018T005234Z-857b3ccd0a36` | synthetic-v0 | **Mocked** baseline: repository config (threshold 0.2), API with Mistral mocked, real RAGFlow |
