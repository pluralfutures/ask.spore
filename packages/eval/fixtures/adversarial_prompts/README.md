# Adversarial workspace instructions (P1a-08)

Synthetic, hostile "additional instructions" blocks, as a tenant admin could save them for a
workspace (each within the 2,000-character cap), and the items they are tested on. Used by
`python -m eval guardrails`; see `packages/eval/README.md`.

- `blocks/NN-<attack>.md`: one block per file, inserted verbatim into the workspace slot. Add a
  block as a new file; the attack name in the file name shows up in the results.
- `contexts.jsonl`: one item per line. `item` names a question of `sets/synthetic-v0.jsonl`;
  `expect` is `answer` (the passages answer it) or `decline` (they do not); `passages` are the
  fixed context, written from the synthetic corpus in `fixtures/corpus/` (`type` html or
  markdown marks a passage as untrusted, as the orchestrator does).

Everything here is invented. No real client text, prompt or query belongs in this folder.
