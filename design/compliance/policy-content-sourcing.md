# Content Sourcing and Takedown Policy — Draft

**DRAFT for owner and counsel review, Oct 22, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 22, 2026 |
| Author | Drafted for owner review (gap found in the Phase 1b document set: the compliance guide's SOC 2 policy list names "content sourcing"; owner request of Oct 22, 2026) |
| Placeholders | [security lead name], [takedown contact email], [privacy contact email], [document store], [date] |
| To finalise, the owner must | (1) fill in the placeholders; (2) have counsel confirm §6 (third-party notices on client files, EU Digital Services Act) and §5.4 (special-category rule); (3) publish the short version of §6 on the trust page; (4) approve and sign; (5) set the review date. |

---

## 1. Purpose and scope

What may enter SporeBot's library, who decides, on what basis, and how content leaves it again. It covers both content models (architecture §15.1):

- **Model 1, platform-gathered:** published third-party PDFs, crawled public web pages and our own DOCX/PPTX analysis, chosen and licensed by us. The test client `cc` uses only this model.
- **Model 2, client-supplied:** files a client chooses and sends for its own workspaces, under terms §6A and DPA clause 7A. Designed, not built (P1b-19 step 2); offered only as an add-on within a larger project with the client.

It sits under `policy-information-security.md`. The legal reasoning is in the compliance guide (sections on licensing and its addenda) and `legitimate-interest-assessment.md`; this policy states the rules.

## 2. Principles

1. **Nothing reaches the index without an approved register row.** The source register is the licensing defence and the index for erasure (architecture §6.1).
2. **Every tag belongs to one tenant.** A tag may be shared between workspaces of the same tenant and never across tenants, for any content; the same file may therefore sit in the index several times under different tenants (owner decision Oct 22, 2026; architecture §15.4).
3. **Excerpts and links, not copies.** Users see cited excerpts; a file is downloadable only where its `downloadable` flag is set, never by default.
4. **Clients' files are clients' data.** We process them as processor, use them only for that client, and never mix them with another tenant's content.

## 3. Roles

| Role | Does | Holder today |
| --- | --- | --- |
| Content editor | Proposes sources (files, URLs, sites), records metadata and licence basis, registers client-supplied batches | The owner |
| Content reviewer | Approves or rejects proposals, decides downloadability for model 1, applies the special-category rule, withdraws sources, handles takedowns | The owner |
| Security lead | Owns this policy, reviews the request log quarterly | The owner |

The two content roles are recorded in `content_roles` (P1b-01). With one internal user, a reviewer may approve their own proposal; the approval is audited with both roles named, and the no-self-approval rule returns when a second internal user exists (owner decision Oct 21, 2026; `backlog.md`).

## 4. Model 1: platform-gathered content

### 4.1 Licence review before proposal

- **Third-party PDFs and documents.** Check the publisher's licence or terms for text-and-data mining, AI use, excerpt display and redistribution. Where in doubt, obtain written permission or exclude the document. Record the basis as text in the register (required); attach a licence or permission letter where one exists (optional, decision 10 of Oct 22, 2026).
- **Downloadable flag.** Set only where the licence permits redistribution from our domain; in practice our own analyses. A wrongly flagged third-party file is a redistribution of someone else's work (risk R-07).
- **Own analysis.** Basis "own work"; downloadable where we choose.

### 4.2 Crawling

- Honour robots.txt (including crawl delay), the EU text-and-data-mining reservation (`/.well-known/tdmrep.json`, `tdm-reservation` header or meta tag; DSM Directive Art. 4) and `noai`/`noindex`/`none` directives. A reserving site is not crawled.
- Per-site allow decision, scope rules (path allow and deny patterns), schedule and page cap in the console (P1b-04). A reviewer's approval of a site covers the pages each crawl adds or changes, recorded in the reviewer's name; withdrawals stay per page (decision 8).
- Descriptive user agent with a contact address; rate limit per host; never crawl behind a login; strip tracking parameters.
- Network safety: the crawler connects only to the address it resolved and re-checks on every redirect; private, loopback, link-local and metadata addresses are refused (decision 9, P1b-18). No site outside our own list is registered before that fix is live.
- Pages matching special-category path patterns are skipped and listed unless a reviewer whitelists the path (P1b-04).

### 4.3 Approval, ingestion, re-ingestion

- Status flow `proposed → approved → ingested → withdrawn`, with `rejected` and `failed` (findings A1-1). Every transition is audited with before and after values.
- Linking an ingested source into further tags needs a reviewer (findings A1-6). Tags offered are only those of the tenant concerned.
- A new file at an existing canonical link does not replace the old document automatically; the console flags "possible replacement" and the reviewer chooses replace or keep both (decision 4).
- Review dates: each source carries one; at review, confirm the licence still applies and the content is still relevant, or withdraw.

## 5. Model 2: client-supplied content

Designed, not built; applies once P1b-19 step 2 passes its tests (architecture §15).

### 5.1 Intake

- The client signs terms §6A and DPA clause 7A first. Files arrive by a link to a file share the client controls (for example SharePoint) or by email, once the mailbox provider is listed as a sub-processor (until then, links only; `backlog.md`). PDF, DOCX, PPTX, Markdown and HTML; up to 500 MB per file and 100 files per batch. A larger file is stored but not ingested until we have consulted the client, possibly after OCR or Markdown conversion.
- Each file or batch comes with the client's signed declaration: right to supply, downloadability, personal data of people other than its staff, and which case of the special-category rule (§5.4) applies. The reference goes into `client_declaration_ref`; the declaration is kept in [document store] for 5 years after the contract ends.
- Copies we hold outside the platform are kept only on encrypted devices and deleted within 30 days after the contract ends, or earlier on withdrawal or request.

### 5.2 Review

The reviewer checks format and size, that the declaration covers the file, the file's **relevance to the purpose of the target workspace**, the tags (owned by the supplying tenant only) and the special-category rule. The reviewer does not assess the client's rights; the client warrants them and indemnifies us (terms §6A.2, §6A.3). A rejected file is reported to the client with the reason.

### 5.3 Placement and use

- Register basis `client-supplied` with the supplying tenant; only that tenant's tags; de-duplication never merges it with a platform source or another tenant's source.
- Downloadable only to that tenant's users, only as its declaration says.
- Used only to serve that client, including answer-quality testing in its own workspaces with scores only kept, unless its contract excludes it. Never used for another client, for training, or for our own purposes.

### 5.4 Special-category data (both models)

GDPR Art. 9 data (racial or ethnic origin, political opinions, religious or philosophical beliefs, trade-union membership, genetic or biometric data, health, sex life or sexual orientation) and Art. 10 criminal-offence data, about an identifiable person:

| Case | Example | Rule |
| --- | --- | --- |
| (a) Made public by the person themselves | An autobiography stating the author's ethnic origin | Accepted (Art. 9(2)(e)); other GDPR duties still apply |
| (b) Revealed about a person by someone else | A biography or press article | Accepted only after the reviewer's check and, for client files, the client's written confirmation of its legal basis; otherwise refused or a redacted copy ingested |
| (c) Not public | HR, medical or union-membership records | Refused |

Aggregate figures that identify no one are not personal data. Nothing accepted is used to search or profile people by these traits.

## 6. Withdrawal, takedown and notice procedure

### 6.1 How to reach us

Notices and requests go to [takedown contact email] (or [privacy contact email]), published in the privacy notice and on the trust page. Every request is entered in the request log (`request-log-template.md`) the day it arrives.

### 6.2 Request types and windows

| Request | Who sends it | What we do | Window |
| --- | --- | --- | --- |
| Publisher takedown of platform content | Rights holder | Verify the claim and the source; withdraw with the scope that matches the claim (§6.3); blank stored excerpts (licence grounds, decision 5) | 10 working days (Monday to Friday) from a valid request |
| Licence breach we find ourselves | Us | Withdraw at once | Immediately |
| Objection or erasure by a person named in platform content | Data subject | Assess under the LIA; withdraw the document or ingest a redacted copy; reply with the decision and reasons | 30 days |
| Access request about platform content | Data subject | Search the register and corpus for the name; reply | One month |
| Client's own withdrawal of a client-supplied file | Client (tenant admin, in writing) | Withdraw; delete our copies outside the platform; keep stored excerpts labelled "withdrawn" | 10 working days |
| Third-party rights notice on a client-supplied file | Rights holder | §6.4 | Suspension at once on a valid notice |
| Request by a person named in a client-supplied file | Data subject | Forward to the client (controller) without undue delay; tell the requester we forwarded it; do not name the client unless it agrees or a court or authority requires it | Forward without undue delay |
| Client's request to drop a platform source from its own package | Client | One-tenant withdrawal (§6.3) | 10 working days |

### 6.3 Scope of a withdrawal

A takedown or withdrawal of a platform source is recorded with a scope: **all tenants** (for example the publisher's licence ends) or **one tenant** (for example a licence that covers one client's use but not another's). A one-tenant withdrawal removes only that tenant's copy, caches and stored citations; the source turns `withdrawn` when its last copy is withdrawn (owner decision Oct 22, 2026; architecture §15.7). Adding a withdrawn tenant's copy back needs a reviewer and is audited.

Every withdrawal runs the withdrawal job (P1b-03): documents deleted from the datasets in scope, answer caches citing them purged, register row or copy marked withdrawn with reason, date and takedown reference, stored citations flagged.

### 6.4 Third-party notices on client-supplied files

1. **Valid notice only:** it identifies the file, explains the right claimed and gives the claimant's contact details. Otherwise, ask for the missing details; do not act.
2. **Suspend first:** on a valid notice, remove the file from search, the file list and downloads at once; keep its stored copy for 30 days.
3. **Statement of reasons** to the client: the file, the claim, the claimant unless the law prevents it, the action taken and how to contest it.
4. **Outcome:** if the claim is withdrawn or rejected within 30 days, restore the file; otherwise delete it as on withdrawal and blank stored excerpts (rights grounds).
5. Requests from people named in the file are not notices under this section; they follow the forwarding route in §6.2.

Counsel to confirm whether the EU Digital Services Act treats us as a hosting service for client files, and so whether Art. 16 (notice mechanism) and Art. 17 (statement of reasons) apply formally; the procedure above is written to meet them either way.

### 6.5 Records

The request log holds the request, our decision, the reasons and the dates. It contains personal data and is kept in [document store], never in the repository, for 3 years after the request is closed (records of processing C6, open question E3).

## 7. Controls and evidence

| Control | Evidence | Status |
| --- | --- | --- |
| Approved register row before ingestion (CC2.3, C1.1) | `sources` status constraint; ingestion job refuses unapproved sources (P1b-02 tests) | Built in Phase 1b |
| Audited content roles and transitions (CC6.3) | `content_roles`; `source.*` audit events | Built in Phase 1b |
| robots.txt, TDM reservation, `noai` honoured (DSM Art. 4) | Crawler tests (P1b-04) | Built in Phase 1b |
| Crawler network safety (CC6.6) | P1b-18 tests | Phase 1b (P1b-18) |
| Withdrawal cascade and takedown timer (CC6.5) | P1b-03 tests; takedown queue | Built in Phase 1b |
| Takedown scope per tenant | Per-copy status; scoped withdrawal tests | Designed (P1b-19 step 2) |
| Tenant-owned tags, client-supplied placement rule (CC6.1, C1.1) | Negative tests in architecture §15.12 | Designed (P1b-19 step 2) |
| Client declarations on file | Register reference; [document store] | Process, from the first model-2 client |
| Request log and windows met (P5.1, P6.1 if in scope) | `request-log-template.md` entries | Process |
| Quarterly review of the log and of register review dates | Sign-off in [document store] | Not started |

## 8. Review and approval

Reviewed once a year and when a content model, the crawler rules or the takedown windows change. Next review: [date].

Approved by: [security lead name], for Estefania Simon-Sasyk y Otro CB, date [date].
