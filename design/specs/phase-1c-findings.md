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

### 3.2 P1c-14 register and crawl follow-ups

One migration, **0060** (`0060_site_withdrawal`, `down_revision` 0041), for (a) only. Commits
3a5fc78 (e), 9e8c359 (d), 2d200c5 (c), 1ff944a (a, b).

| # | Spec says | Built |
| --- | --- | --- |
| D-5 | (a) "Site-level 'withdraw site' in the console and CLI: withdraws every page of the site (reusing the per-page withdrawal job), retires the site row (no further scheduled crawls), audited" | `app.content.sites.withdraw_site`, a reviewer's action: `POST /api/v1/content/sites/{id}/withdraw` (reason required), a "Withdraw site" form on the site page, and `ask-spore sites withdraw <site_id> --as <email> --reason … [--wait]`. In one transaction the site becomes **`withdrawn`** (a new status value: migration 0060 also adds `withdrawn_at` and `withdrawal_reason`, required together by a check constraint, as on `sources`) with `next_crawl_at` cleared; every live page becomes `blocked` with reason `site_withdrawn`; every `ingested` or `failed` row of the site gets the reason and its own `withdraw_source` job (the per-page job, unchanged), audited `source.withdrawal_requested` with `method: site_withdrawal`; the site gets `site.withdrawn` (before and after status and schedule, roles, the number of jobs; never the reason text). Scheduled crawls, "crawl now" and a queued `crawl_site` job all need `approved`, so nothing crawls the site again. A row still being ingested is withdrawn when its ingestion finishes, because its page is no longer live (the Phase 1b rule, findings 1b A2-7). **Not in the spec:** a crawl running at the moment of withdrawal stops at its next page (each visit checks the site's status, and a page is admitted only under a share lock on the site row, so the withdrawal waits for an admission in progress and then withdraws it), and keeps no next crawl. A migration was needed because `sites.status` had a check constraint without a retired state; reusing `rejected` would have shown a retired site as a declined proposal. The downgrade turns a withdrawn site into `rejected` with its reason as the review note. |
| D-6 | (b) "'Restore' for a withdrawn crawled page so the next crawl takes it again, audited" | `app.content.sites.restore_page`, a reviewer's action on the page's withdrawn register row: `POST /api/v1/content/sources/{id}/restore`, a "Restore page" button on a withdrawn crawled source, and `ask-spore sources restore <source_id> --as <email>`. The page's `site_pages` row goes from `blocked` (`withdrawn`) to `removed` (`restored`), which the crawler treats like any page it has not got: the next crawl that meets it records a new register row (approved in the site approver's name, as every page) and ingests it. The withdrawn row stays withdrawn (its history and citations untouched). Refused: before the withdrawal job has run (`not_withdrawn`), for a page withdrawn by the crawler rather than a reviewer or of a withdrawn site (`not_a_withdrawn_page`, `site_not_approved`), and for a URL any version of which had a takedown recorded (`taken_down`: the Phase 1b rule that such a URL stays out holds). Audited `source.restored`. |
| D-7 | (c) "Clean-up of an interrupted re-tag job as an interrupted first ingestion already is (findings 1b A1-11)" | No migration: `add_tags` now maps each new upload on the row as it happens, as `ingest_source` does. A document mapped in the dataset of a synced tag the row does not hold belongs to an unfinished re-tag, and the next re-tag of the source deletes it from RAGFlow before uploading (`_clean_unfinished_retag`); keys that are not a synced dataset's ID (Phase 0 mappings) are never touched. A failed re-tag unmaps what it deleted and keeps mapped only the documents whose deletion failed, so the next re-tag or a withdrawal removes them (before, they were named in the error and tracked by nothing). Consequence, as for a first ingestion (A1-11): while a re-tag parses, its new dataset's chunks can already be retrieved and cited by tenants with the new tag, whose addition a reviewer approved. |
| D-8 | (d) Decision 3: "a new file replaces an existing document only when both the canonical link and the title match; a link match with a different title is flagged to the reviewer as a possible replacement" | `register.exact_replacement`: at proposal, a file with the canonical link **and** the title (compared ignoring case and runs of spaces) of exactly one ingested, non-crawled source, which no other proposal is already replacing, records that source as `supersedes_id`; the approval then needs no choice and is audited `replaces` with `method: same_link_and_title`, and the A1 supersession path runs once the new file is ingested. So a manifest re-run with a corrected file at the same link and title re-ingests it (`--approve-as`), which decision 4 of Oct 22 had stopped. A link match under another title, or a link two ingested sources share under the same title, is flagged as before (`possible_replacement`, `replacement_choice_required`). The approval checks the match again: a target withdrawn or taken by another proposal meanwhile falls back to the reviewer's choice. **The reviewer may still choose "keep both"** for a same-title match (an override, audited `keep_both`); the decision says when a file replaces, and does not forbid keeping both. `ProposeOut` gains `replaces`, and the console's propose result names the source replaced. |
| D-9 | (e) Decision 3: "the stored excerpt of a citation is blanked on every withdrawal, not only licence ones; the citation stays, labelled withdrawn; adjust the database trigger … only if it blocks this, via a migration" | The withdrawal job blanks the excerpts of the source and of the earlier versions it replaced on **every withdrawal** (a reviewer's, a takedown on any grounds, a crawl's removal, a site withdrawal, a crawled page gone before its ingestion finished); the audit event's `excerpts_blanked` is true for all of them. **The trigger does not block it** (it lets `askspore_content` write only `''`, whatever the grounds), so no migration. **A supersession keeps the excerpt**: the document is still in the corpus under its new version, and decision 3 speaks of withdrawals (question 2). **Not in the spec:** when a document is withdrawn, its earlier versions' citations are labelled withdrawn too (they were only "superseded"), so a citation of any version of a withdrawn document shows "withdrawn" with the blanked-excerpt note; found by the site-withdrawal test, where a page's second version superseded the first while the site was being withdrawn. `takedown_licence_grounds` stays recorded (queue, audit) but no longer changes the withdrawal; the CLI help and the console label say so, and the chat's note now reads "The quoted passage was removed because the source was withdrawn." Architecture §6.3 and §15.7 updated. |

Tests (all against PostgreSQL 16, RAGFlow and the site faked): `test_sites`:
`test_a_withdrawn_site_leaves_no_page_in_any_dataset_and_no_schedule` (two datasets, a page
version still being ingested, a client tenant's citation; afterwards no document of the site
in the fake RAGFlow, every row withdrawn, no live page, `next_crawl_at` empty, a past due date
queues nothing, "crawl now" and a stale queued crawl refused, the audit trail with no reason
text), `test_a_crawl_running_when_its_site_is_withdrawn_admits_nothing_more` (fails without the
guard), `test_a_restored_page_is_crawled_again`,
`test_a_taken_down_or_unwithdrawn_page_cannot_be_restored`; `test_jobs`:
`test_an_interrupted_retag_is_cleaned_up_before_the_next_upload` (a worker stopped mid-parse,
then the job put back) and `test_a_failed_retag_unmaps_what_it_deleted_and_keeps_what_it_could_not`
(both fail on the old code); `test_withdraw`:
`test_the_same_link_and_title_replace_the_old_version_without_a_choice` (CLI path),
`test_an_automatic_replacement_can_be_overridden_or_falls_back_to_a_choice`, the existing
link-only tests now with another title, `test_withdrawal_on_licence_grounds_blanks_the_stored_excerpts`
(unchanged) and `test_every_other_withdrawal_blanks_the_stored_excerpts_too` (plain and
non-licence takedown, across tenants, the superseded version kept until its document is
withdrawn), `test_cli_site_withdrawal_and_restore_flags`; `test_content_console`: the two new
routes are refused to tenant admins and users like every content route, and
`test_a_reviewer_withdraws_a_site_and_restores_a_page_from_the_console` (editor refused,
codes, audit), `test_the_same_link_and_title_replace_without_a_choice`; web unit tests for the
propose result, the withdrawn-site summary, the two new page reasons and the "Withdraw site"
form.

### 3.3 P1c-15 backlog triage

One commit, no code. Each struck line names what delivered it; each was checked against the
code or the findings first (the crawler, the consent gate migration, `design/compliance/`,
the committed eval results and the gate).

| | Lines | Notes |
| --- | --- | --- |
| **Struck** | **28** | 21 delivered by Phase 1b or earlier: re-ingestion and withdrawal (P1b-03), stored own-analysis files (P1a-14, P1b-02), the approval step and content console (P1b-01, P1b-05), crawler policy and publication dates (P1b-04), the Oct 18 Phase 1b line (console, approval flow, retention jobs, SSO connectors), operator spend visibility (P1b-12), the consent gate (P1b-10), per-IP rate limit, session refresh, sign-out revocation, `no_binding`, the Authentik blueprint (P1b-08), platform mail (P1b-11), the four document-set lines (P1b-09, drafted), the one-tenant console (P1b-12), the deploy version in the cache key (P1b-13 e), the committed Phase 0 eval results (owner decision Oct 21, enforced by the gate since P1b-15 b). 5 delivered by this branch (P1c-14 a to e: the re-ingestion title and excerpt decisions, the re-tag clean-up, restore, withdraw site). 1 moved to P1c-07 (resend invitation). 1 closed by owner decision (branch protection, decision 2 of Oct 23). Three struck lines were delivered only in part; their remainders are carried as new Phase 2 lines (two-host deployment; per-path TDMRep rules and site terms review; the support-access policy and staff checklist). |
| **Re-tagged** | **29** | 25 as Phase 1c with their item (P1c-01 to P1c-09, P1c-11, P1c-13), including the two owner-held items (P1b-13 a and b) marked as not build items; 4 as Phase 2 (the RAGFlow UI path, Object Storage, guardrail eval scoring of fixed sentences, the no-self-approval rule). The truncation line, counted under Phase 1c, keeps its struck part; its open tail is split between P1c-09 (the stored flag) and Phase 2 (an eval run on the output cap). The Phase 1a relevance-check line is re-tagged as the P1c-13 fallback with a pointer to 3.1.4. |
| **Left as is** | **23** | 12 lines struck before this triage and 11 open lines already tagged Phase 2. |
| **Added** | **5** | The three carried remainders above and two ideas from this build: reinstating a withdrawn site (its start URL is unique, so it cannot be registered again), and the future of `takedown_licence_grounds` now that every withdrawal blanks excerpts. |

Not struck although the brief lists it: none. The **vector weight, judge model and eval gate**
and the **eval harness OIDC path, reasoning tokens and retention lines** were already struck
before this triage (left as is). The Phase 1a Playwright flake line was **not** struck
although P1b-13 f fixed a race in it (findings 1b D12): the Phase 1c spec carries it again as
P1c-11, so it is re-tagged there.

### 3.4 Checks run on this branch

All on the branch head, in the session container (PostgreSQL 16.15 started with
`pg_ctlcluster 16 main start`, role `askspore` as in CI,
`TEST_ADMIN_DATABASE_URL=postgresql://askspore:ci-only-password@localhost:5432/postgres`,
`REQUIRE_DB_TESTS=1`). Last line of each:

| Check | Last line |
| --- | --- |
| `uv run --directory apps/api ruff check .` | `All checks passed!` |
| `uv run --directory apps/api ruff format --check .` | `201 files already formatted` |
| `uv run --directory apps/api mypy app` | `Success: no issues found in 105 source files` |
| `uv run --directory apps/api pytest` (with the database) | `1371 passed, 1 deselected in 151.31s (0:02:31)` (`test_ragflow_integration` deselected, as in CI) |
| the same without the database | `614 passed, 757 skipped, 1 deselected in 8.93s` |
| `uv run --directory packages/eval ruff check .`, `ruff format --check .`, `mypy` | `All checks passed!`, `37 files already formatted`, `Success: no issues found in 16 source files` |
| `uv run --directory packages/eval pytest` | `89 passed in 2.63s` |
| `uv run --directory packages/eval python -m eval gate` | `**Pass.**` (no run newer than the baseline is committed) |
| `python -m eval guardrails --mock` on a config copy naming `corpus_only/v6` | `No block degrades any metric beyond the threshold.` (every block 100 in both modes; the same on v5) |
| `pnpm --dir apps/web lint`, `typecheck`, `test` | `All matched files use Prettier code style!`, `tsc -b` clean, `Tests  102 passed (102)` |
| `pnpm --dir apps/web test:e2e` (`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`) | `13 passed` |

`apps/api/openapi.json` and `apps/web/src/api/schema.d.ts` were regenerated for the new
routes and fields. No API dependency changed, so `packages/eval/uv.lock` is unchanged. No eval
result was committed. Not run: anything that needs the Instance, RAGFlow or a provider key
(3.1.3).

### 3.5 Questions for the owner

1. **hc-v1-039, 055, 058 (P1c-13, after the live run).** If v6 passes the acceptance rule of
   3.1.3, switch to it. If it fixes some but not all three items, or regresses: accept the
   remaining items as known limits (recorded here), or fund the relevance check of 3.1.4 as
   its own spec item (one extra model call per `corpus_only` question, about 0.25 to 0.3
   cents and up to 1.5 s)?
2. **Excerpts on supersession (P1c-14 e).** Decision 3 blanks excerpts on every withdrawal;
   this build keeps them when a re-ingested version replaces a document (the citation shows
   "superseded" and the document is still in the corpus), and blanks every version's
   excerpts once the document itself is withdrawn. Confirm, or blank on supersession too.
3. **Keep both on a same-title match (P1c-14 d).** A file with the same link and title
   replaces the old source without a choice, but the reviewer may still choose "keep both"
   at approval. Confirm the override, or make the replacement unconditional.
4. **A withdrawn site is final (P1c-14 a).** Its start URL stays taken (unique), so the same
   site cannot be registered again; reinstating one is a Phase 2 backlog line. Confirm, or
   ask for a reinstate action now (it would go back to `proposed` for a reviewer).
5. **Restore waits for the next crawl (P1c-14 b).** A restored page comes back when its
   site's next scheduled or requested crawl meets it; restore does not queue a crawl itself
   (a reviewer can press "Crawl now"). Confirm, or queue a crawl on restore.
6. **`takedown_licence_grounds` (P1c-14 e).** It no longer changes what a withdrawal does.
   Keep it as a record on the takedown queue (as built), or drop the flag and its checkbox
   (a migration; backlog line)?
7. **Migration number.** 0060 on 0041 as briefed; if Groups A to C also chain on 0041, the
   integration step re-parents one `down_revision` line.
