# AI Transparency Note

**Version 1. Approved by counsel, Oct 26, 2026 (owner's report). Served at /legal once `ASKSPORE_LEGAL=published`.**

| | |
| --- | --- |
| Status | **APPROVED by counsel, Oct 26, 2026** (version 1) |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | none (filled in by the owner, Oct 26, 2026) |
| Revision | Oct 22, 2026, **DRAFT**: one clause in step 1 of "How an answer is made" for organisations that supply documents (P1b-19 step 1, architecture §15); drop it for the test client |
| To finalise, the owner must | (1) fill in the placeholders; (2) confirm the model list matches the catalogue at publication (`config/models.toml`); (3) remove the external-models paragraph's "not enabled" sentence once a tenant is enabled; (4) link this note from the in-app AI notice and the consent gate (P1b-10); (5) have counsel check it against EU AI Act Art. 50 (ai-act-technical-documentation.md §3). |

Plain text below the line is the note shown to users.

---

## About the answers in SporeBot

**You are using an AI system.** Answers in SporeBot are written by an AI language model, not by a person. Every answer carries the notice "AI-generated, verify against cited sources."

### How an answer is made

1. Your question is used to search a curated library of published reports, public websites and our own analysis and documents your organisation supplied, if any. The library depends on the workspace you chose.
2. The most relevant passages, your question and the recent turns of the conversation go to the AI model.
3. The model writes an answer and cites the passages it used. Click a citation to see the publisher, title, date and page, and the excerpt.

### What to keep in mind

- **Check the sources.** The model can misread a passage or combine passages wrongly. Treat the answer as a starting point and verify important points against the cited source.
- **Uncited means not from the library.** In the default mode, the answer only uses the library. If no passage supports an answer, you get a short reply saying so, not a guess. If your organisation has enabled the "General knowledge" mode, the model may add what it knows; those sentences have no citation, are visibly marked, and the answer shows a "General knowledge" banner. They are more likely to be wrong or out of date.
- **The library has limits.** It covers what we have collected, up to each source's publication date. Something missing from the library is not proof that it does not exist.
- **Not advice.** Answers are research assistance. They are not legal, financial, medical or other professional advice and should not be the only basis for decisions about people.

### Which models answer

By default, models run by Scaleway in the European Union: DeepSeek V4.1 Flash and Qwen 3.8 27B. You may pick the model when you start a conversation, among those your organisation has enabled. The companies that run the models are listed on the [sub-processor list](/legal/sub-processors).

Some models can "reason" before answering. If you switch reasoning on, the answer shows a "reasoning on" badge. The reasoning text itself is never shown or stored. (DeepSeek V4.1 Flash is offered with reasoning off only.)

**External models.** If your organisation has asked for them, you may also see Claude Opus 5.5 and GPT-6.1 Sol. The model picker marks them "served outside the EU": your conversation is then sent to Amazon Web Services or Microsoft Azure, which may process it outside the EU. Today they are not enabled for any organisation.

### What we send and what we keep

- The model receives our instructions, your workspace's instructions, library excerpts, recent conversation turns and your question. **No name, email address or account identifier.**
- Model providers are required not to keep your request and not to train on it.
- **We do not use your questions or conversations to train or improve any model.**
- Conversations are kept for 30 days at most, or less if your organisation set a shorter period. You can delete a conversation at any time.

More in our privacy notice: [privacy notice](/legal/privacy). Questions: privacyanddata@myceliumgastronomy.com.

Estefania Simon-Sasyk y Otro CB · Version 1, last updated 22 October 2026
