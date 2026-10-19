# config

- `models.toml` — provider endpoints, pinned model names, the outbound host allow-list split into `eu_hosts` and `external_hosts` (P0-03, P1a-09), and the model `[[catalogue]]` (P1a-09): per model its provider, display name, reasoning switch kind, price per million tokens in and out in cents of its `currency` (`EUR` or `USD`; the usage ledger converts USD at `[pricing] usd_to_eur`, which startup requires when a USD entry exists), optionally `price_placeholder = true` while prices are placeholders (the API logs a warning per such entry at startup; none is now), whether it is served outside the EU, and for OpenRouter entries an optional provider pin (`provider_order`, `provider_only`) sent with zero-data-retention routing always applied on top.
- `prompts/<name>/<version>.md` — versioned prompt templates (P0-12). The active version of each is set in `models.toml` `[prompts]`; a released version file is never edited, a change is a new version plus an eval run.
  - `corpus_only/` — system prompt for corpus-only answers. From `v2` (P1a-06) it carries the workspace's additional-instructions slot, below.
  - `general_knowledge/` — system prompt for the general-knowledge answer mode (P1a-06), with the same slot.
  - `rewrite/` — system prompt for turning a follow-up into a standalone search query.
  - `judge/` — faithfulness judge of the eval harness (`packages/eval`, P0-18); not used by the API.

## The workspace-instructions slot (P1a-06)

A mode prompt may contain one section between `{{#workspace_instructions}}` and `{{/workspace_instructions}}`, holding one `{{workspace_instructions}}` placeholder. `app.chat.prompts.render_system` replaces the placeholder with the workspace's active additional instructions (tenant-authored, capped at 2,000 characters, HTML-escaped so the text cannot close its `<workspace_instructions>` element), or drops the whole section when there are none. The text around the placeholder, which tells the model that the block is tenant-authored and lower priority than the platform rules, lives in the prompt file like every other instruction. Startup refuses a prompt whose slot markers are malformed.
