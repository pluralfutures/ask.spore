# Privacy Notice — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Revision | Oct 22, 2026, **DRAFT**: documents supplied by customers (§1, §2, §4, §7 and new §13), P1b-19 step 1. Publish the §13 text only once a customer supplies documents (P1b-19 step 2 built); until then the library holds no customer documents and §13 is omitted |
| Placeholders | [registered address], [DPO or privacy contact name], [privacy contact email], [security contact email], [takedown contact email], [website address], [supervisory authority], [Member State], [date], [version], [link to sub-processor list], [link to LIA summary], plus the retention and website values marked in §3 |
| To finalise, the owner must | (1) fill in the entity, contacts and supervisory authority; (2) decide whether a DPO is required or a privacy contact suffices (open-questions.md); (3) confirm the website and contact-form processing in §3 matches what the public website actually does (analytics, cookies); (4) have counsel check §4 against the LIA and the Art. 14(5)(b) reasoning; (5) publish at a stable URL linked from the sign-in page and the consent gate (P1b-10); (6) set the version number the consent gate records (the wording goes in `config/consent/<version>.md`, the version in `[consent] version` of `config/models.toml`; P1b-10, findings E1-5). |

Plain text below the line is the notice.

---

## About this notice

SporeBot is a research assistant. It answers questions from a curated library of published reports, public websites and our own analysis, and, for some customers, documents the customer supplied for its own use, and shows the sources for every answer. It is run by **Estefania Simon-Sasyk y Otro CB**, a comunidad de bienes under Spanish law trading as Mycelium Gastronomy Network, NIF E19824093, [registered address] ("**we**").

This notice explains what personal data we handle and why. It has two parts:

- **Part A** is for people who use SporeBot through their employer, and for people who contact us.
- **Part B** is for people who are named or quoted in the public sources in our library (GDPR Article 14), and explains who is responsible for documents our customers supply (§13).

Privacy contact: [DPO or privacy contact name], [privacy contact email].

Version [version], last updated [date].

## Part A — Users of SporeBot and people who contact us

### 1. Who decides about your data

If you use SporeBot, your employer (our customer) signed up for it and invited you. **Your employer is the controller** of your account, your sign-in events, your questions and your conversations, and of any documents it supplied to SporeBot for its own workspaces. We process that data **on your employer's behalf and on its instructions**, under a data processing agreement. For requests about that data (access, correction, deletion), contact your employer first; we will help them answer.

**We are the controller** only for:

- our own operational and security logs of the service (technical metadata, no question or answer text);
- the library of public sources (Part B);
- messages you send us directly (support, privacy, security or takedown requests).

The rest of Part A describes both, so that you can see the whole picture.

### 2. What we process on your employer's behalf

| Data | What it is | How long it is kept |
| --- | --- | --- |
| Account | Email address, name if given, role, status, last sign-in time and method | While your employer uses the service |
| Sign-in | Single-use sign-in links (valid 15 minutes), session tokens, sign-in and sign-out events, the IP address at sign-in | Links expire after 15 minutes; events as audit records, below |
| Questions and conversations | Your questions, the answers, the sources cited, your feedback, the model and settings you chose | 30 days at most; your employer can set a shorter period (1 to 30 days). From Phase 1b (P1b-14) your employer can also choose not to keep history at all |
| Downloads | Which file you downloaded and when | Audit record, below |
| Documents your employer supplied (only if it does) | The files your employer sent us for its workspaces, their text and search index | Until your employer withdraws them, and deleted when it stops using the service. Only your employer's users can search or download them |
| Audit records | Who signed in, administrative actions, when a question was asked and which sources were cited, downloads. Never the text of a question or answer | 12 months |

Today, conversations past their retention period no longer appear anywhere in the service. They are removed from the database by a scheduled clean-up job from Phase 1b (P1b-14).

We do **not** use your questions or conversations to train or improve any AI model, we do not sell them, and we never show one customer's questions or answers to another customer. Our staff do not read conversations, except where your employer asks for support on a specific conversation; such access is time-boxed and logged.

### 3. What we process as controller

| Purpose | Data | Legal basis | Retention |
| --- | --- | --- | --- |
| Keeping the service secure and working | Technical logs: request ID, time, status, latency, token counts, error codes, a pseudonymous user or customer ID. No question, answer or prompt text, no email content | Our legitimate interest in running a secure, reliable service (Art. 6(1)(f)) | [30 days for application logs — owner to confirm]; security-relevant audit records 12 months |
| Aggregated service metrics | Counts per customer (questions per day, active users, cost per model). No text | Legitimate interest (Art. 6(1)(f)) | [24 months], aggregated |
| Answering your messages to us | Your name, email address, the content of your message | Legitimate interest in responding; legal obligation where you exercise a GDPR right (Art. 6(1)(c)) | [2 years] after the matter is closed |
| Our website | [describe: no analytics cookies / the analytics tool used — owner to confirm] | [consent / legitimate interest] | [ ] |

### 4. Where your data is processed and who receives it

Everything we store is hosted by **Scaleway in Paris, France**: the application, the database, the search index, the files you can download, our logs and backups.

By default, questions are answered by AI models run by **Scaleway in Paris** (DeepSeek V4.1 Flash and Qwen 3.8 27B). What the model receives: our fixed instructions, your workspace's instructions written by your employer, excerpts from the library (including, where your employer supplied documents, excerpts from them), recent turns of the conversation and your question. **No name, email address or account identifier is sent to the model.**

Sign-in emails are sent by **Scaleway Transactional Email in Paris**. It receives your email address and the email containing the link, nothing else.

**External models (only if your employer chose them).** Your employer can ask us to enable Claude Opus 5.5 and GPT-6.1 Sol. We do this only after your employer has signed for it. If you then pick one of these models for a conversation, that conversation's content (as above, still without identifiers) is sent through OpenRouter's EU endpoint to Amazon Web Services (for Claude) or Microsoft Azure (for GPT). These providers may process it outside the EU, including in the United States. The model picker labels these models "served outside the EU". The transfer relies on the EU Standard Contractual Clauses, and every request asks the providers to keep nothing (zero data retention) and not to use it for training. Today external models are not enabled for any customer.

The full list of companies that process data for us is at [link to sub-processor list].

### 5. Your rights

You can ask for access to, correction or deletion of your data, restriction of processing, data portability, and you can object to processing based on legitimate interests. For data we process for your employer, we pass your request to your employer and help it respond. For data we control, write to [privacy contact email]; we answer within one month.

You can also complain to a data protection supervisory authority, in particular in the EU country where you live or work. Ours is [supervisory authority], [Member State].

### 6. Security

Each customer's data is kept apart by database rules that are tested on every change. Logs never contain your questions or answers. Sign-in links work once, for 15 minutes, only after you press a button on the page they open, and only in the browser that asked for them. Data is encrypted in transit. Details are in our security documentation, available to customers on request.

## Part B — People named in the public sources in our library

### 7. Why you may be in our library

Our library contains published third-party material (research reports, industry studies, company publications, public websites) and our own analysis of it. Some customers also supply their own documents for their own workspaces; section 13 explains that part. Published material often names people: authors, executives, spokespeople, people quoted or mentioned. We did not get this information from you, so GDPR Article 14 applies. **We are the controller** of this data.

### 8. What we hold

| | |
| --- | --- |
| Categories | Names, job titles, employers, professional statements and quotes, and other information that appears in the published text about a person in a professional or public capacity |
| Not intended | Special categories (health, political opinions, religion and similar). We do not seek them out. An automatic filter that skips web pages likely to contain them is added from Phase 1b (P1b-04); until then sources are chosen by hand |
| Sources | Publicly available reports and documents from their publishers, and public websites that do not opt out of text and data mining (we respect robots.txt and the machine-readable reservation under EU copyright law). A summary of the publishers in our library is available on request at [privacy contact email] |
| What we do with it | Split the text into short passages, index them for search, show passages with their source (publisher, title, date, page) to our customers' users when relevant to a question, and offer downloads of a file only where its licence allows |
| Who sees it | Users of our business customers, through answers and citations. The text is also sent, as excerpts, to the AI model answering a question (section 4) |

### 9. Purpose and legal basis

Purpose: providing a research service that helps businesses find and cite published information.

Legal basis: our **legitimate interests** and those of our customers in research based on published sources (Art. 6(1)(f)). We assessed that the use is limited to what was already published, in its professional context, and that it is proportionate. The assessment is summarised at [link to LIA summary] and available in full on request.

### 10. Why we publish this notice instead of contacting you

The library contains many documents from many publishers, and they name many people in passing. We usually have no contact details for them, and finding and contacting each would require a disproportionate effort compared with the limited impact of indexing what is already published (Art. 14(5)(b)). We therefore make this notice public, keep a register of every source, and act quickly on requests.

### 11. How long we keep it

As long as the source stays licensed and relevant to our library. Each source has a review date in our register. When a source is withdrawn, its passages are removed from the search index; answers already given keep their citation, marked as withdrawn. From Phase 1b (P1b-03) this withdrawal runs as one automated job across every index and cache; until then it is carried out by hand.

### 12. Your rights and how to ask for removal

You can ask what we hold about you, ask for correction, **object** to our use of it, or ask for its **erasure**. We assess each request and, where it succeeds, remove the document or replace it with a copy without your data **within 30 days**, and tell you what we decided and why.

Write to [takedown contact email] (or [privacy contact email]), naming the document or web page if you can. We may ask for information to confirm the request concerns you.

Publishers who want their content removed can use the same address. We act on publisher takedown requests within 10 working days.

You can also complain to a supervisory authority (section 5).

### 13. Documents supplied by our customers

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15).*

Some customers send us documents to be searched in their own workspaces: their reports, material they hold a licence for, or internal documents. Only that customer's users can search or download them; no other customer sees them.

If you are named in such a document, **the customer that supplied it is the controller** of your personal data in it. We process it on that customer's behalf and on its instructions, under a data processing agreement. The customer decides what it supplies and why, and is responsible for having a lawful basis for it and for informing you; Part B sections 7 to 12 do not apply to these documents.

If you write to us about a document a customer supplied, we pass your request to that customer without undue delay and help it respond. We will tell you that we have done so, but we cannot tell you which customer supplied a document without its agreement. [*Counsel: confirm this wording; see open-questions J.*]

What happens to these documents: their text is split into passages and indexed, shown with citations to the customer's own users, and sent as excerpts to the AI model answering their questions (section 4), under the same rules as the rest of the library: no names or account identifiers are added, and providers keep nothing. Documents are deleted when the customer withdraws them or stops using the service.

## Contact

Estefania Simon-Sasyk y Otro CB, [registered address]

- Privacy: [privacy contact email]
- Removal of content or personal data from our library: [takedown contact email]
- Security reports: [security contact email]

---

## Notes for the owner (delete before publishing)

1. **Roles.** Part A follows the Oct 20, 2026 roles decision (processor for all client user data, including accounts and sign-in events). If counsel prefers that we are controller for account data, §1 to §3 change.
2. **Log retention** (§3) is not fixed in any design document for application logs; the audit retention of 12 months is. Pick a number. Note that the audit table rejects DELETE for every role, so the 12-month limit needs a disposal procedure that is not built yet (policy-data-retention-disposal.md).
3. **Backups** are not mentioned with a retention period because they are owner-run outside the spec (30 days recommended). Add "backups up to [30] days" once fixed.
4. **Takedown windows** (§12): 30 days for data-subject erasure is the compliance guide's figure; 10 working days for publishers is P1b-03's. The SLA timer is from Phase 1b (P1b-03); confirm the windows can be met by hand until then.
5. **Downloads** (§8): by owner decision of Oct 20, 2026, third-party files in the test corpus are downloadable where their manifest row says so. Confirm the licence basis per source before publishing "only where its licence allows".
6. **Encryption at rest** is not claimed in §6 because the Instance volume encryption is unconfirmed; add it once confirmed.
7. **Customer-supplied documents** (§13, Oct 22, 2026): drafted ahead of the build (P1b-19 step 2). Counsel to confirm that the processor role and the forward-to-the-customer route are right for people named in client files, and whether we may tell a requester which customer supplied a document (open-questions J).
