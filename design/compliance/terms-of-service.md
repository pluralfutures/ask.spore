# Terms of Service and Master Services Agreement — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT — not for signature. Counsel must review before it is sent to [Client] or signed.** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 22, 2026, **DRAFT**: §6A (client-supplied documents: warranty, indemnity, downloads, withdrawal), with changes to §1.1, §1.2, §3.1, §6.1, §11, §13.3, §13.4 and Annex A.8, for customers that supply their own documents (P1b-19 step 1). For the test client, which supplies nothing, keep §1.2 option (a) and delete §6A and A.8. Placeholders added: [5] (working days), [secure transfer method], [max file size], [max files per batch], [indemnity cap] |
| Placeholders | [registered address], [Client], [Client legal name], [date], [price], [currency], [term], [notice period], [liability cap], [Member State], [courts], [privacy contact email], [security contact email], [support email], [support hours], [response time], [payment days], [seats], [workspace name], [tag], [spend cap], [acceptance reference] |
| To finalise, the owner must | (1) fill in the placeholders, in particular prices, liability cap, governing law and support terms; (2) decide the open points in "Notes for the owner"; (3) have counsel review, especially §8 (output disclaimer), §11 (liability) and §13 (termination); (4) attach the signed DPA (`client-dpa-draft.md`) and the order form (Annex A); (5) check every statement in Annex A against what is enabled in the operator console at signature. |

---

These terms ("**Agreement**") are between **Estefania Simon-Sasyk y Otro CB**, a comunidad de bienes under Spanish law trading as Mycelium Gastronomy Network, NIF E19824093, [registered address] ("**Provider**", "**we**"), and the customer named in the order form ("**Customer**"). The Agreement consists of these terms, the order form (Annex A) and the Data Processing Agreement ("**DPA**"). If they conflict: the DPA wins on data protection, then the order form, then these terms.

## 1. The service

1.1 SporeBot (the "**Service**") is an online research assistant. It answers questions from a curated library of published third-party sources and the Provider's own analysis and, where §6A applies, documents the Customer supplies (together the "**Library**") and cites the passages it used.

1.2 *Owner: choose one.* (a) Customer does not upload documents. The Library is selected, licensed and maintained by the Provider. (b) *DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).* The Customer chooses and supplies documents for its workspaces under §6A ("**Customer Documents**"). The Provider may supplement them with published or open-source content it selects, licenses and maintains.

1.3 The Customer's access is organised in **workspaces**. Each workspace searches a set of content tags (the "**Package**") listed in the order form. The Provider decides, server-side, which parts of the Library a workspace may search.

1.4 The Provider may update the Library, models and features, provided the Service as a whole does not materially decline in what the order form describes. Model changes that alter where data is processed follow the DPA's sub-processor notice clause.

## 2. Accounts and access

2.1 The Customer names one or more **administrators**. Administrators invite and deactivate users from the Customer's verified email domains, set the default answer mode and model per workspace among those enabled, edit workspace instructions and shorten chat-history retention.

2.2 Users sign in with a single-use link sent by email. From Phase 1b (P1b-07) users may instead sign in through the Customer's identity provider (Microsoft Entra ID, Google Workspace, or a generic OIDC or SAML provider), configured by the Provider with the Customer's IT contact.

2.3 The number of user accounts is limited to the seats in the order form. Accounts are personal and may not be shared.

2.4 The Customer is responsible for its users' compliance with this Agreement and for removing users who leave.

## 3. Customer data and confidentiality of questions

3.1 "**Customer Data**" means users' account data, sign-in events, questions, conversations, feedback, workspace instructions written by the Customer, download records and, where §6A applies, Customer Documents with their parsed text and index entries. The Customer owns Customer Data. The Provider processes it as processor under the DPA.

3.2 **Query confidentiality.** Questions, answers and conversations are never visible to, shared with or used to answer the questions of any other customer.

3.3 **No training.** The Provider does not use Customer Data to train or fine-tune any AI model, and requires its model providers not to do so. Customer Data is used to improve the Service only as aggregated, pseudonymised metrics with a minimum group size, never as text.

3.4 The Provider does not sell Customer Data.

## 4. Answer modes and models

4.1 **Answer modes.** "Corpus only" is the default: answers use only the Library. "General knowledge", where enabled in the order form, lets the model add its own knowledge where the Library is silent. Modes are enabled only by the Provider.

4.2 **Models.** By default, answers are generated by models hosted by Scaleway in Paris, France. The models available to the Customer are listed in the order form.

4.3 **External models** (Claude Opus 5.5 and GPT-6.1 Sol at the date of these terms) are offered only if (a) the order form lists them, (b) the Customer has signed the acceptance in Annex 4 of the DPA, and (c) the Provider has enabled them. They are reached through OpenRouter with zero-data-retention routing on every request and may be processed outside the EU, as described in the DPA. A monthly spend cap applies; once reached, new conversations use the workspace's default model until the next month.

## 5. Acceptable use

5.1 The Customer and its users must not:

- extract the Library in bulk, systematically download or reproduce its content, or use the Service to build a competing collection, dataset or model;
- redistribute files downloaded from the Service, or passages shown in it, beyond the Customer's internal research use, except as the publisher's own terms allow;
- try to obtain the Service's instructions, bypass its limits, or access another customer's data;
- enter special-category personal data (health, political opinions, religion and similar) or data about criminal offences in questions;
- use the Service as the sole basis for decisions with legal or similarly significant effects on individuals, or for any use listed as high-risk in Annex III of the EU AI Act, without telling the Provider first;
- use the Service unlawfully or to harm others.

5.2 The Service limits downloads per user per day and sign-in link requests per user. Further rate limits and automated detection of bulk extraction may be added; the Provider will apply them reasonably.

## 6. Downloads

6.1 Users see the list of files in each workspace's Library. A file can be downloaded only where the Provider has marked it downloadable on the basis of its licence, or, for a Customer Document, where the Customer's declaration allows it (§6A.4); other files link to the publisher.

6.2 Downloads are for the Customer's internal research use. Each download is recorded. Download links work once, for 60 seconds; the daily cap per user is [50].

6.3 The Customer gains no ownership of Library content. Rights in third-party content stay with their owners.

## 6A. Customer Documents

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).* *Only for a customer that supplies documents.*

6A.1 **Supply.** The Customer may send the Provider documents for its workspaces (PDF, DOCX or PPTX, up to [max file size] MB each and [max files per batch] per batch) by [secure transfer method], each file or batch with a written declaration naming the files and stating, for each, whether the Customer's users may download it and whether it contains personal data of people other than the Customer's staff. The Provider reviews each file for its relevance to the purpose of the workspace it is meant for, and may refuse a file that is outside these limits, lacks a declaration, does not fit that purpose, or appears to contain special-category data, and says why.

6A.2 **Customer's warranty.** The Customer warrants that it owns or is licensed to supply each Customer Document for use in the Service as described in this Agreement and the DPA: parsing and indexing it, sending excerpts to the language models named in the DPA, showing excerpts with citations to the Customer's users and, where declared, letting them download it; that doing so infringes no third party's rights or confidentiality obligation; and that any personal data in it may lawfully be processed this way (DPA clause 7A.4).

6A.3 **Indemnity.** The Customer indemnifies the Provider against third-party claims, and the reasonable costs of defending them, to the extent they arise from a Customer Document or its use in the Service as permitted by this Agreement. The Provider notifies the Customer of a claim promptly, lets the Customer control its defence and does not settle it without the Customer's consent. [*Counsel: whether the indemnity is capped, at [indemnity cap], or uncapped; see §11.3.*]

6A.4 **Downloads.** A Customer Document is downloadable only by the Customer's own users and only where the Customer's declaration says so. The Customer may change this by written instruction.

6A.5 **Isolation.** Customer Documents are searched, listed and downloadable only within the Customer's own workspaces and are never available to another customer. The Provider uses them only to provide the Service to the Customer and never to train any model. This includes testing the quality of answers on Customer Documents: test questions are written from them and run in the Customer's own workspaces, and the Provider keeps only the resulting scores, never the questions, answers or document text. The Customer may exclude this testing in the order form (A.8).

6A.6 **Withdrawal.** On the Customer's written request the Provider withdraws a Customer Document within [5] working days. If the Provider receives a third party's notice that a Customer Document infringes its rights, the Provider may withdraw the document at once, without waiting for the Customer's instruction, and tells the Customer without undue delay. The Customer may contest the claim; once it is resolved in the Customer's favour, the Provider re-ingests the document on the Customer's instruction.

6A.7 **Ownership.** The Customer keeps all rights in Customer Documents and grants the Provider, for the term, the non-exclusive right to use them as described in §6A.2, solely to provide the Service to the Customer.

## 7. Support and availability

7.1 Support is provided as set out in the order form, by email to [support email] during [support hours].

7.2 The Service runs on a single server in Paris. The Provider aims for the availability in the order form but gives no service-level credit unless the order form says so. Planned maintenance is announced to administrators in advance where practical.

## 8. Output disclaimer

8.1 Answers are generated by AI language models. They can be incomplete, outdated or wrong, including where they cite a source. Sentences without a citation in "General knowledge" mode come from the model, not from the Library, and are marked as such.

8.2 The Service is research assistance. It is not legal, financial, medical or other professional advice. The Customer is responsible for checking answers against the cited sources before relying on them.

8.3 The Provider does not warrant the accuracy, completeness or currency of third-party content in the Library.

## 9. Intellectual property

9.1 The Provider owns the Service and its own analysis. The Customer receives a non-exclusive, non-transferable right for its users to use the Service and its outputs for the Customer's internal business purposes during the term.

9.2 As between the parties, the Customer may use the answers it receives for its internal purposes, subject to the rights of third parties in quoted content and to §5.

## 10. Suspension

The Provider may suspend a user or the Customer, with notice where practical, if: use breaches §5; it is needed to protect the Service, other customers or Library rights holders; or invoices are more than [payment days] days overdue after a reminder. The Provider lifts the suspension once the cause is resolved.

## 11. Liability

11.1 Neither party limits liability for death or personal injury caused by negligence, fraud, or anything that cannot be limited by law.

11.2 Otherwise, each party's total liability under this Agreement in any 12 months is limited to [liability cap — e.g. the fees paid in the previous 12 months]. Neither party is liable for indirect or consequential loss, loss of profit or loss of data beyond restoring it from the latest backup.

11.3 [Counsel: whether data-protection and confidentiality breaches carry a separate, higher cap, and whether the Customer's indemnity in §6A.3 sits outside the cap in §11.2.]

## 12. Fees

12.1 The Customer pays the fees in the order form. Invoices are due within [payment days] days. Prices exclude VAT.

12.2 Usage of external models above the included amount is invoiced as set out in the order form, never above the spend cap.

## 13. Term and termination

13.1 The Agreement starts on the order form's start date and runs for [term], renewing for further periods of [term] unless either party gives [notice period] notice.

13.2 Either party may terminate for material breach not remedied within 30 days of notice, or immediately if the other becomes insolvent.

13.3 **Export window.** Before the end date, administrators may ask for an export of user accounts and the conversations still within retention. The Provider supplies it in a common machine-readable format within [10] working days of the request, provided the request is made at least [15] days before the end date. Conversation export inside the Service is not available yet; the export is produced by the Provider. Where §6A applies, the Provider also returns, on request, the copies of Customer Documents it holds, as received.

13.4 **Deletion.** After termination the Provider deletes Customer Data, including every Customer Document with its parsed text and index entries, as set out in the DPA (clause 10.5) and the offboarding procedure (`offboarding-pack.md`), and issues a certificate of deletion. From Phase 1b (P1b-14) this runs as a tested per-customer purge job that produces the certificate's figures.

13.5 Sections 3, 8, 9.2, 11 and 13.4 survive termination.

## 14. General

14.1 Neither party may assign this Agreement without the other's consent, except to a successor of its whole business on notice.

14.2 Notices are in writing to the addresses in the order form; email counts.

14.3 Governing law: the law of [Member State]. Courts: [courts].

---

## Annex A — Order form

| | |
| --- | --- |
| Customer | [Client legal name], [registered address], company number [ ] |
| Provider | Estefania Simon-Sasyk y Otro CB |
| Start date / term | [date] / [term] |
| Administrator(s) | [name, email] |
| IT contact (SSO, mail) | [name, email] |
| Verified email domains | [domain] |

### A.1 Package

| Workspace | Content tags | Notes |
| --- | --- | --- |
| [workspace name] | [tag], [shared tag] | |
| [workspace name] | [tag], [shared tag] | |
| [workspace name] | [tag], [shared tag] | |

*Owner: for the test client, three workspaces (`team1-healthcare-gpo`, `team2-college-universities`, `team3-commercial-restaurants`), each with its own tag plus `cc-shared` (empty until P1b-13d decides its files). Use the Customer-facing names here.*

### A.2 Seats and fees

| Item | Quantity | Price |
| --- | --- | --- |
| User seats | [seats] | [price] per seat per month |
| Platform fee | 1 | [price] per month |
| Onboarding and SSO setup | 1 | [price] one-off |
| External-model usage | as used, up to the spend cap | [price / included amount] |

Currency: [currency]. Payment terms: [payment days] days.

### A.3 Answer modes

| Mode | Enabled | Default |
| --- | --- | --- |
| Corpus only | Yes | [Yes] |
| General knowledge | [Yes/No] | [ ] |
| Web search | Not offered (Phase 2) | — |

### A.4 Models

| Model | Hosted by | Location | Enabled |
| --- | --- | --- | --- |
| DeepSeek V4.1 Flash (`deepseek-v4.1-flash`, reasoning off only) | Scaleway | Paris, France | [Yes] |
| Qwen 3.8 27B (`qwen3.8-27b`) | Scaleway | Paris, France | [Yes] |
| Claude Opus 5.5 (`anthropic/claude-opus-5.5`) — **external** | OpenRouter → Amazon Bedrock | May be outside the EU (see DPA clause 6) | [No / Yes, once DPA Annex 4 is signed] |
| GPT-6.1 Sol (`openai/gpt-6.1-sol`) — **external** | OpenRouter → Microsoft Azure | May be outside the EU (see DPA clause 6) | [No / Yes, once DPA Annex 4 is signed] |

External-models spend cap: [spend cap, e.g. EUR 30.00] per month. Acceptance reference: [acceptance reference].

### A.5 Retention

Chat-history retention: [30] days (maximum 30; the Customer's administrators may set 1 to 30). A "no history" setting (0 days) is available from Phase 1b (P1b-14). Audit records: 12 months.

### A.6 Sign-in

| | |
| --- | --- |
| Emailed sign-in links | [On] (default on) |
| SSO | [None / Microsoft Entra ID / Google Workspace / OIDC / SAML], from Phase 1b (P1b-07) |
| Second factor for administrators | From Phase 1b (P1b-08) |

### A.7 Support

| | |
| --- | --- |
| Channel | [support email] |
| Hours | [support hours] |
| First response | [response time] |
| Security contact | [security contact email] |
| Privacy contact | [privacy contact email] |
| Target availability | [ ]% per month, no service credits unless stated: [ ] |

### A.8 Customer Documents (only where §6A applies)

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).*

| | |
| --- | --- |
| Customer Documents supplied | [Yes / No] |
| Customer-owned content tags (one per workspace, plus an optional common tag for the Customer's workspaces only) | [tag], [tag] |
| Platform content supplementing them | [None / platform tags listed in A.1] |
| Transfer method for files | [secure transfer method] |
| Limits | [max file size] MB per file, [max files per batch] per batch; PDF, DOCX, PPTX |
| Withdrawal on request | Within [5] working days |
| Answer-quality testing on Customer Documents (§6A.5) | [Allowed (default) / Excluded] |

Signed for [Client]: name [ ], title [ ], date [ ]

Signed for Estefania Simon-Sasyk y Otro CB: name [ ], title [ ], date [ ]

---

## Notes for the owner (delete before sending)

1. **Self-serve terms vs MSA.** This draft is written as an MSA with an order form for business customers. Users still accept the privacy and use notice at first sign-in (P1b-10); counsel to confirm that the click-through notice does not need to repeat these terms.
2. **Export window** (§13.3): the export is a manual job today; no export feature is built. Confirm the [10] working days is realistic, and whether to offer it at all given the 30-day retention.
3. **Availability** (§7.2): one Instance, owner-run backups, no monitoring stack (backlog). Do not promise a numeric SLA with credits until the two-host deployment.
4. **Downloads** (§6): by owner decision of Oct 20, 2026, third-party test-corpus files are downloadable where their manifest row says so. The redistribution right sits with the licence of each file; the cap of 50 per day is in `config/models.toml`.
5. **Rate limits** (§5.2): only the sign-in link limit and the download cap exist. No per-user query limit or bulk-extraction detection is built.
6. **Customer Documents** (§6A, Oct 22, 2026): drafted ahead of the build (P1b-19 step 2); offer §6A only once that build and its isolation tests pass. Counsel to review §6A.2 and §6A.3 (warranty, indemnity, cap) and the interplay with §11. Open points in `open-questions.md` section J.
