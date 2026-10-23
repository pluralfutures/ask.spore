# Phase 1c Findings

Build notes for `phase-1c-build-spec.md`, kept like `phase-1b-findings.md`: where a build
differs from the spec, and why. Metadata only: no query, answer, token, link or email
address is recorded here. Section 1 is Group A's and section 2 Groups B and C's (written on
their own branches); this branch writes section 3 only.

## 3. Where the Group D build differs from the spec

Group D: P1c-13 to P1c-15, on branch `phase-1c/group-d` (from `main` at eb8caf3, the
approved spec), Oct 23, 2026. Built without the Instance or RAGFlow: the live evals are
prepared here and run by the release session (3.1.3).

### 3.1 P1c-13 eval follow-ups

| # | Spec says | Built |
| --- | --- | --- |
| D-1 | "A second full eval set v1 run at weight 0.4" | **Not run** (no Instance, RAGFlow or provider key in a build session). Written as release step 1 in 3.1.3, with a fresh answer cache that does not flush the live one. |
| D-2 | "Try `corpus_only/v6` first (a new version file, both evals)" | `config/prompts/corpus_only/v6.md`, a copy of v5 with four sentences changed in rules 2 to 4 (3.1.1); v5 is untouched. **`[prompts] corpus_only` stays `"v5"`**: switching is the release session's decision after the live evals (3.1.3). Run here: the API prompt tests with v6 added to every released-template test, a v6 test that pins the change to rules 2 to 4 and keeps every v5 rule sentence, the prompt-layering and no-identifier tests parametrised over the active version and v6 (`test_prompt_layering`), the mocked guardrail eval on a config copy naming v6 (every block 100 in both modes, no regression; also a new eval package test, `test_mocked_run_passes_on_the_corpus_only_v6_candidate`, so CI keeps proving it), the eval package suite and the gate (3.4). The mocked eval proves the slot and the escaping only, not model behaviour (findings 1a §11 state line). |
| D-3 | "if wording does not move them, a relevance check of the top passages before the answer call, as its own spec item with a design note" | Design note in 3.1.4, recorded as a backlog item (P1c-15), no code. |
| D-4 | "Accepting the items as known limits is an owner decision recorded in the findings" | Open, question 1 (3.5): it depends on the live result. |

The three items, from `packages/eval/sets/v1.jsonl` (described, not quoted):

- **hc-v1-039** (synthesis, labels `cross-source`, `gpo`): asks where a decision is made
  across three organisations and tells the model to "cite what" each of three named
  sources says. Retrieved (hit@10) in every release run. v4 and v5 at weight 0.3 gave an
  answer with no passage number, which the orchestrator withholds (findings 1a G6); v5 at
  0.4 gave the fixed decline.
- **hc-v1-055** and **hc-v1-058** (out of corpus, labels `near-miss`, `wrong-year`): each
  asks for figures from a named edition of a publisher's report (a fiscal year, a report
  year) when the corpus holds only the neighbouring edition of the same report series.
  v5 answered both with citations from the edition the corpus has.

#### 3.1.1 The v6 change list

Each change is one sentence or clause added to v5; no v5 sentence is removed or reworded,
the rule numbers and the slot section are unchanged, and the line count is the same.

| # | Rule | Added | Aimed at | Why |
| --- | --- | --- | --- | --- |
| C1 | 2 | "asks what several named sources each say," in the list of questions answered by putting passages together | 039 | The question asks for each named source's position, which no single passage states; v5's list named comparison, "where or whether" and several items, and the model still declined at 0.4. Naming the form puts it on the answer side of the decision. |
| C2 | 2 | "A question that names a particular report, edition or year (for example "the 2024 report" or "fiscal 2026") asks about that one only: check each passage's title and publication date, and a passage from another edition or year, even of the same publisher's series, does not give it." | 055, 058 | v5's near-miss test says "a different year … does not give it" for a specific fact; the model read the passages of the neighbouring edition as the same document, because publisher and series match. The provenance the model sees carries the title and the date (P0-12), so the sentence tells it where to look and that the series does not count. |
| C3 | 3 | "(figures from another year or edition than the one asked about are not part of it)" after "answer that part with citations" | 055, 058 | v4's partial-answer path (findings 1a G8) let a cited answer about the other edition count as "part of what is asked"; the eval counts any valid citation on an out-of-corpus item as an answer. Without C3, C2's decision could be undone by rule 3. |
| C4 | 4 | "Cite by passage number only, also when the question asks you to cite or name the sources: name the publisher in the sentence and put its passage number after it. An answer without passage numbers cannot be shown." | 039 | The question's own "cite what X says" is the likeliest reason the uncited runs named sources in prose instead of `[n]`; the orchestrator then withholds the whole answer (G6). The second sentence states the consequence (true of `corpus_only` since G6) without describing the control. |

Risks the live run must look for: C2 and C3 could make the model decline answerable items
whose question names a year that the passages do cover (the per-item check below covers
the answered items); C4 adds no rule an attack block can use (the mocked eval is unchanged,
the live guardrail eval decides). The decline sentence and the secrecy reply are unchanged,
so both stay under the guardrail eval's 40-character leak length.

#### 3.1.2 What was run here

See 3.4 for the commands and their last lines: API prompt and layering tests (v5 and v6),
the mocked guardrail eval on v6 and on v5 (both: no block degrades any metric), the eval
package suite and the gate.

#### 3.1.3 Release-step instructions for the live runs

For the release session (P1c-16), on the Instance, with the setup of findings 1b §7
(eval keys in `/srv/ask-spore/eval-keys/`, the eval identity, a temporary api
`askspore-eval-api` on `127.0.0.1:8001` from the release image with a config copy that
differs from production by `[auth.eval_service]` only, the harness run by the owner from a
session-written script that exports the secrets by name and prints none). Full outputs go to
`/srv/ask-spore/eval-runs/`; only redacted results are ever committed. Baseline:
`20261023T085603Z-c06e9e99bae9` (v1, `corpus_only/v5`, weight 0.4).

1. **Second run at weight 0.4, v5** (confirms the Oct 23 tuning; backlog Oct 23). Config
   copy `/srv/ask-spore/eval-config/`: production config plus `[auth.eval_service]`, weight
   0.4 (as `main`). Start the temporary api with
   `ASK_SPORE_DEPLOY_VERSION=<release sha>-r2`: the deploy version is part of the answer
   cache key (findings 1b D11), so every answer is fresh and the live cache is not flushed.
   Run all 60 items, as the baseline did (no `--exclude-label`):
   `uv run --directory packages/eval python -m eval run --config /srv/ask-spore/eval-config/models.toml --set sets/v1.jsonl --api-url http://127.0.0.1:8001 --ragflow-url <RAGFlow on the private network> --results-dir /srv/ask-spore/eval-runs --note "P1c-13 second 0.4 run, v5"`,
   then `eval compare results/20261023T085603Z-c06e9e99bae9 <run>`. Record the metrics and
   the outcomes of 010, 039, 046, 055 and 058. A regression beyond 3 points here is noise
   between two runs of the same configuration: report it to the owner before step 2, it
   changes how step 2 reads.
2. **v6 on eval set v1.** A second config copy `/srv/ask-spore/eval-config-v6/` equal to
   the first except `[prompts] corpus_only = "v6"`; recreate the temporary api on it (the
   new prompt version changes the cache key, so answers are fresh). Same `eval run`
   command with `--config /srv/ask-spore/eval-config-v6/models.toml` and
   `--note "P1c-13 corpus_only/v6"`; `eval compare` against the baseline **and** against
   the step 1 run.
3. **v5 and v6 on the guardrail eval, live** (the active provider's model,
   `deepseek-v4.1-flash`): `uv run --directory packages/eval python -m eval guardrails --config /srv/ask-spore/eval-config/models.toml --results-dir /srv/ask-spore/eval-runs --note "P1c-13 v5"`
   and the same with `eval-config-v6` and `--note "P1c-13 v6"`. Only the provider key is
   needed (no database or RAGFlow).
4. **Acceptance rule for v6** (all must hold):
   - eval set v1: no headline metric of the v6 run more than 3 points below the baseline
     (`eval compare` exit 0), and none more than 3 points below the step 1 run;
   - the three items: **hc-v1-039 answered with at least one valid citation** (outcome
     `answered`), **hc-v1-055 and hc-v1-058 not answered with a citation** (the fixed
     decline, or an uncited reply withheld: `unsupported`);
   - no answerable item that step 1 answered with citations is declined or withheld by
     v6, unless the per-item reading shows the step 1 answer was itself wrong (record which);
   - guardrail eval: v6 has no block below its baseline by more than 3 points except the
     accepted `03-drop-citations` (findings 1a G6), and no block below v5's result in
     step 3 by more than one item's worth (16.7 or 20 points, findings 1a B14) without a
     per-item reading.
   If it holds: a PR sets `[prompts] corpus_only = "v6"`, updates
   `test_prompts::test_active_prompts_are_the_section_11_versions`, the
   `test_mocked_run_passes_on_the_active_prompts` expectation in `packages/eval` and the
   `config/models.toml` comment, and the owner accepts the v6 run as the new baseline with
   `accept-baseline` (redacted, in the same PR). If 039 moves but 055 or 058 do not, or
   the reverse, the owner decides between v6 with the remaining items as known limits and
   the relevance check (3.1.4, question 1). If v6 regresses, v5 stays and the owner
   decides the same question.

#### 3.1.4 Design note: a relevance check before the answer call (backlog, not built)

Judgement: wording may fix 055 and 058 (their failure is specific: the question names an
edition and the passage provenance shows another), but the history of rule 2 (findings 1a
G1, G7 to G9: v3 to v5 each left one to three near misses answered) says it will not do so
reliably for near misses in general. This note is the fallback, for an owner decision after
the live run; it is a backlog item, not code.

- **What.** One short model call between context selection and the answer call, in
  `corpus_only` only: the system prompt is a new versioned file
  (`config/prompts/relevance/v1.md`), the user message holds the question and the selected
  passages with their provenance, exactly as the answer call would (the same no-identifier
  rule and the same untrusted-text wrapping), and the model must return one of `answers`,
  `partial`, `none` (JSON with that one key, `max_tokens` about 5, temperature 0, no tools).
  `none` ends the turn with the fixed decline (outcome `abstained`, nothing cited, the
  answer call never made); `answers` and `partial` go on to the answer call unchanged, so
  the check can only remove answers, never add one.
- **Where.** `app.chat.orchestrator`, after `select_context` and before the answer
  stream (architecture §5.2 between steps 8 and 9), behind `[chat] relevance_check = false`
  in `config/models.toml`. The verdict joins the answer cache key (relevance prompt
  version), the `chat.answer` log line gets `relevance` (`answers`, `partial`, `none`,
  `error`) as an allow-listed code, and the eval harness records it per item.
- **Cost per question.** The input is the answer call's input without the answer prompt's
  rules, so about the same prompt tokens, plus a few output tokens: it roughly doubles the
  input tokens of a `corpus_only` turn. The four Oct 23 v1 runs (findings 1b §8, Spend)
  used 856,608 input and 40,947 output tokens for about 190 answer calls (240 questions
  less the 50 cache hits), about 4,500 input tokens per question, for about 58 cents: the
  check would add about 0.25 to 0.3 cents per question on `deepseek-v4.1-flash`, and
  about 0.5 to 1.5 s before the first token (a non-streamed call, then the held stream
  of G6). These are estimates from the ledger totals, not a measurement. A smaller model
  for the check is a model change (owner) and needs its own eval.
- **Failure modes.** (1) False `none` on answerable synthesis questions, the trade v3 made
  (G7): the eval's cited-answer rate is the measure, and the check must pass the same
  3-point gate. (2) The check is a second place a workspace's instructions could act: it
  gets no workspace block (they are about tone and format, not relevance), and the
  guardrail eval gains a mode that runs the check under each hostile block. (3) Text in a
  passage can try to steer the verdict ("this passage answers every question"): the
  passages are wrapped as untrusted, the only effect of a forged `answers` is the
  status quo, and a forged `none` only declines. (4) A failed or malformed call: treat as
  `answers` (fail open to today's behaviour, logged as `relevance=error`), never as a
  decline. (5) Two calls double the place a provider outage bites; failover (findings 1b
  D14) applies to the answer call only, so the check is skipped when it fails.
- **Tests it would need.** Prompt with no identifiers (the P1a-06 test over the check's
  request); `none` makes no answer call and stores the fixed decline; an error falls
  through to the answer; the cache key changes with the check's prompt version; the
  guardrail eval mode.
