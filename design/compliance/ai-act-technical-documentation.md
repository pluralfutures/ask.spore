# EU AI Act Technical Documentation — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** (internal; not published) |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [Product name], [Owner legal entity name], [AI literacy owner], [document store], [date], [review date] |
| To finalise, the owner must | (1) have counsel confirm the classification in §2 and the role in §2.3; (2) decide the Art. 50(2) marking question in §3 (open-questions.md); (3) name who owns AI literacy (§4) and record the training; (4) set a review date; (5) re-run §2 whenever a reassessment trigger in §2.4 occurs. |

---

## 1. Scope

This file records how [Product name] is classified under Regulation (EU) 2024/1689 (the "**AI Act**"), which duties follow, and the technical documentation we keep to show we meet them. The Compliance & Privacy Design Guide asks for "technical documentation of model, provider, sources and evaluation" (§"EU AI Act") even where the Act does not strictly require a formal file; this is that document.

## 2. Classification

### 2.1 What the system does

A retrieval-augmented research assistant. A business user asks a question; the API searches a curated library of published sources and our own analysis, sends the best passages with the question to a language model, and shows the answer with citations. The model has no tools, cannot browse or act, and cannot change any data.

### 2.2 Risk category

| Question | Answer | Reasoning |
| --- | --- | --- |
| Prohibited practice (Art. 5)? | No | No manipulation, social scoring, biometric identification, emotion recognition or predictive policing. The system answers research questions from published text |
| High-risk (Art. 6, Annex I)? | No | Not a safety component of a product under Annex I legislation |
| High-risk (Art. 6(2), Annex III)? | No, as offered | Not designed or marketed for any Annex III use (biometrics, critical infrastructure, education access, employment, essential services and credit, law enforcement, migration, justice, elections). Customers are food-service and research businesses using it for market and sector research. The terms forbid Annex III use without telling us first (`terms-of-service.md` §5.1) |
| Transparency duties (Art. 50)? | Yes | The system interacts with people and generates text (§3) |
| General-purpose AI model (Chapter V)? | We are not a provider | See §2.3 |

Result: **limited-risk AI system** with Art. 50 transparency duties, plus the general AI literacy duty (Art. 4).

### 2.3 Our role

- **Not a GPAI model provider.** We do not train, fine-tune or otherwise modify any model. We call third-party models through APIs: DeepSeek V4.1 Flash and Qwen 3.8 27B hosted by Scaleway, and optionally Claude Opus 5.5 (Anthropic) and GPT-6.1 Sol (OpenAI) through OpenRouter. Their developers carry the Chapter V GPAI obligations.
- **Provider of an AI system.** We integrate those models into [Product name] and offer it under our own name, so we are the provider of the AI system for Art. 50 purposes.
- **Deployer** for our own internal use (content operations, evaluation).
- **Customers are deployers** of the system for their users.

### 2.4 Reassessment triggers

Re-run this classification when any of these happen:

- a customer tells us, or we learn, that outputs are used for an Annex III purpose (for example screening job applicants or assessing creditworthiness);
- we add a capability beyond question answering from text: web search (Phase 2), tools, actions, image or audio generation, decisions about individuals;
- we fine-tune or train a model;
- the Commission issues guidelines or amendments affecting Art. 6 or Art. 50.

## 3. Transparency duties (Art. 50)

| Duty | What it asks | Status on Oct 21, 2026 |
| --- | --- | --- |
| Art. 50(1): people know they interact with an AI system | Inform users unless obvious | **Met.** Every answer carries "AI-generated, verify against cited sources." (`AiNotice`). The user-facing note is `ai-transparency-note.md`; it is linked from the consent gate from Phase 1b (P1b-10) |
| Art. 50(2): machine-readable marking of AI-generated text | Providers of systems generating synthetic text mark outputs in a machine-readable format and make them detectable as AI-generated, unless an exception applies | **Not built.** Answers are labelled for people (notice, mode banner, "General knowledge" marking of uncited sentences, "reasoning on" badge) but carry no machine-readable mark, and the export of a conversation is not built. **Open question for counsel**: whether 50(2) applies to a research assistant whose answers are shown in-app with citations, which exceptions apply, the date from which it applies to us, and whether the Digital Omnibus proposals change that timing. If it applies, candidate measures: a metadata field on every answer in the API response and in any future export, and a marker in copied text |
| Art. 50(4): deployers publishing AI-generated text on matters of public interest | Disclose, unless human review and editorial responsibility | A customer duty, not ours. Mentioned in the transparency note ("verify") and the terms; counsel to decide whether the terms should say it explicitly |
| Art. 50(3) (emotion recognition, biometric categorisation), deep fakes | — | Not applicable |

## 4. AI literacy (Art. 4)

Staff and anyone operating the system on our behalf need sufficient AI literacy. Today the owner is the only internal user. Owner of the duty: [AI literacy owner]. Evidence: a short record of training or reading (this file, the eval findings, the guardrail results) per person, dated, kept at [document store]. Repeat when a person joins (`policy-access-control.md`).

## 5. Technical documentation

### 5.1 System description

| Part | Description | Source of truth |
| --- | --- | --- |
| Web app | React, chat with citations panel, file list per workspace, tenant admin and operator pages | `apps/web` |
| API | FastAPI; query rewrite, retrieval, prompt building, model call, citation check, storage | `apps/api/app` |
| Retrieval | RAGFlow (self-hosted, internal network only), embedding model `bge-m3`, Elasticsearch; dataset IDs resolved server-side from the workspace's tags | `apps/api/app/retrieval`, architecture §4.4 |
| Identity | Authentik (self-hosted), emailed single-use sign-in links; SSO from Phase 1b (P1b-07) | `infra/authentik` |
| Hosting | One Scaleway Instance in Paris (fr-par) | Phase 1b spec, "Deployment target" |

### 5.2 Models and providers

| Model | Provider | Endpoint | Use | Notes |
| --- | --- | --- | --- | --- |
| `deepseek-v4.1-flash` | Scaleway Generative APIs | `api.scaleway.ai` (Paris) | Default answers, query rewrite, eval and judge | Reasoning off only (findings §10 F7) |
| `qwen3.8-27b` | Scaleway Generative APIs | Paris | Answers, user choice | Reasoning on or off (F8) |
| `anthropic/claude-opus-5.5` | OpenRouter → Amazon Bedrock | `eu.openrouter.ai` | Answers, only with the external-models entitlement | Off for every tenant; region pending (C32) |
| `openai/gpt-6.1-sol` | OpenRouter → Microsoft Azure | `eu.openrouter.ai` | Same | Same |

Model names are pinned in `config/models.toml`; `-latest` aliases are refused at startup; hosts are checked against an allow-list split into EU and external hosts. External requests carry zero-data-retention routing and `data_collection: deny`, asserted by tests. Prompts carry no tenant, user or package identifiers (tests listed in `phase-1a-findings.md` §10).

### 5.3 Prompts

Versioned files under `config/prompts/<mode>/<version>.md`; the active version is set in `config/models.toml`. Active on Oct 21, 2026: `corpus_only/v5`, `general_knowledge/v2`. A change is a new version file and an eval run (CLAUDE.md). Rationale for each version is in `phase-1a-findings.md` §11, not in the prompt file, because prompt files are sent verbatim (G5). The workspace's tenant-authored instructions sit in one delimited, escaped slot, capped at 2,000 characters, below the platform rules.

### 5.4 Data: the library

- Sources: published third-party PDFs, crawled public websites and our own DOCX/PPTX analysis. Users upload nothing.
- Each source is a row in the source register (publisher, title, date, canonical link, licence basis, tags, downloadable flag). Approval before ingestion from Phase 1b (P1b-01); crawl rules (robots.txt, TDM reservation) from P1b-04; withdrawal cascade from P1b-03.
- Personal data in sources: `legitimate-interest-assessment.md`, `privacy-notice.md` Part B.

### 5.5 Evaluation

| Eval | What it measures | Latest result (Oct 21, 2026) |
| --- | --- | --- |
| Eval set v1 (58 synthetic questions on the licensed corpus) | Retrieval hit@5/@10, citation precision, faithfulness (LLM judge), abstention on out-of-corpus items, cited-answer rate | `corpus_only/v5`, run `20261021T180011Z-2a59408a3469` against the Phase 0 baseline: hit@5/@10 100, citation precision 81.8 (−1.7), faithfulness 85.9 (+5.0), abstention 80.0 (+70.0), cited-answer rate 97.9 (−2.1). No regression beyond the 3-point gate (findings §11 G9) |
| Guardrail eval (adversarial workspace-instruction blocks, both modes) | Citation validity, cited-answer rate, instruction secrecy | Run `20261021T180354Z-193dd66fbac7-guardrails`: every block 100 in both modes except 03-drop-citations, accepted by the owner on the strength of the code control in §5.6 (G6) |
| Version history | v3 over-abstained (cited-answer 89.6, G7); v4 lost faithfulness (76.5, G8); v5 fixed both (G9) | findings §11 |

Baselines for Phase 1b: `corpus_only/v5` and `general_knowledge/v2` (Phase 1b exit criteria). The eval gate in CI and a separate pinned judge model come from Phase 1b (P1b-15). Committed eval results carry metrics only (findings §12).

### 5.6 Controls in code

- **Uncited answers withheld (G6).** In corpus-only mode the API holds the streamed text until it cites a passage; an answer that never cites one is replaced by a fixed message and is not shown, stored, cached or reused as history.
- **Citations checked.** Only passages actually sent can be cited; chunks from datasets outside the workspace are dropped before the prompt.
- **Truncation.** An answer that stops at the output cap is detected and marked (findings §10 F4).
- **No tools.** No model request sets tools or plugins (tests). Public web text is marked untrusted in the prompt.

### 5.7 Known limitations

- **Abstention is imperfect:** 2 of 10 out-of-corpus test questions still get an answer (G9).
- **Faithfulness is 85.9%:** some answer statements are not fully supported by the cited passage, as judged by an LLM judge that is itself the default model until P1b-15.
- **03-drop-citations:** the prompt alone does not stop a workspace instruction that tells the model to drop citations; the G6 code control does in corpus-only mode. In general-knowledge mode a dropped citation shows as a marked general-knowledge sentence.
- **Small eval sets:** one changed answer moves a guardrail metric by 16.7 to 20 points (findings §11, B14).
- **Evaluated on the default model only.** Qwen and the external models are not covered by the eval set.
- **Language and coverage:** the library is what we collected; questions outside it are declined or, in general-knowledge mode, answered from the model.

### 5.8 Human oversight

Users see the cited excerpt for every claim and are told to verify. The operator enables modes and models per tenant; tenant admins choose defaults. Feedback (thumbs and comment) per answer feeds the eval set after review. Nothing is decided automatically about any person.

### 5.9 Logging and records

Logs are metadata only (no questions, answers or prompts), including error paths (ErrorBoundary, e0435c1). Every message stores model, mode and reasoning flag; the audit log records each query's metadata and cited chunk IDs, append-only, for 12 months.

### 5.10 Change control

Every change is a reviewed pull request with CI (tests, isolation checks, mocked guardrail eval); branch protection with required checks from Phase 1b (P1b-13c). Prompt changes need a new version and an eval run. Model changes: pin, re-check provider terms (`policy-vendor-management.md`), run the evals. See `policy-change-management.md`.

## 6. Review

Review by [review date] and on any trigger in §2.4.

| | Name | Date |
| --- | --- | --- |
| Owner | [ ] | [ ] |
| Counsel reviewed | [ ] | [ ] |
