# config

- `models.toml` — provider endpoints, pinned model names and the EU host allow-list (P0-03).
- `prompts/<name>/<version>.md` — versioned prompt templates (P0-12). The active version of each is set in `models.toml` `[prompts]`; a released version file is never edited, a change is a new version plus an eval run.
  - `corpus_only/` — system prompt for corpus-only answers.
  - `rewrite/` — system prompt for turning a follow-up into a standalone search query.
  - `judge/` — faithfulness judge of the eval harness (`packages/eval`, P0-18); not used by the API.
