# Eval results

One folder per harness run, `<UTC timestamp>-<git sha>/`, holding `results.json` (configuration,
metrics, per-item records) and `summary.md`. Never edit a run; compare two with
`python -m eval compare <base> <new>`.

| Run | Set | What |
| --- | --- | --- |
| `20261018T005234Z-857b3ccd0a36` | synthetic-v0 | **Mocked** baseline: repository config (threshold 0.2), API with Mistral mocked, real RAGFlow |
| `20261018T005524Z-1f29494499ba` | synthetic-v0 | **Mocked**, threshold 0.25 (findings section 5) |
| `20261018T005642Z-1f29494499ba` | synthetic-v0 | **Mocked**, threshold 0.30 (findings section 5) |
