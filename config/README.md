# config

- `models.toml` — provider endpoints, pinned model names, the outbound host allow-list split into `eu_hosts` and `external_hosts` (P0-03, P1a-09), and the model `[[catalogue]]` (P1a-09): per model its provider, display name, reasoning switch kind, price per million tokens in and out (euro cents) and whether it is served outside the EU.
- `prompts/<name>/<version>.md` — versioned prompt templates (P0-12). The active version of each is set in `models.toml` `[prompts]`; a released version file is never edited, a change is a new version plus an eval run.
  - `corpus_only/` — system prompt for corpus-only answers.
  - `rewrite/` — system prompt for turning a follow-up into a standalone search query.
  - `judge/` — faithfulness judge of the eval harness (`packages/eval`, P0-18); not used by the API.
