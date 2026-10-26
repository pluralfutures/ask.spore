# Legitimate Interest Assessment — Public-Source Corpus — Draft

**DRAFT for owner and counsel review, Oct 21, 2026**

| | |
| --- | --- |
| Status | **DRAFT** |
| Date | Oct 21, 2026 |
| Author | Drafted for owner review (spec item P1b-09) |
| Placeholders | [date] |
| To finalise, the owner must | (1) confirm the purpose description in §1; (2) confirm the safeguards marked "from Phase 1b" are acceptable as planned, or hold ingestion of new crawled sites until they ship; (3) have counsel review the balancing test and the Art. 14(5)(b) reasoning; (4) sign §7 and set the review date. |

---

## 1. What this covers

Processing of personal data that appears in:

- published third-party documents we add to the library (reports, studies, filings);
- public web pages our crawler fetches;
- our own DOCX and PPTX analysis.

The people concerned are mostly authors, company executives, spokespeople and people quoted. We are the controller (owner decision of Oct 20, 2026). Clients' questions and conversations are not covered here; we process those as processor.

*DRAFT addition, Oct 22, 2026 (P1b-19 step 1; architecture §15):* documents a client supplies for its own workspaces are not covered either. We process them as processor on the client's instructions; the client is controller and needs its own legal basis and Art. 14 transparency for people named in them. Public content we gather to supplement a client stays within this assessment.

## 2. Purpose test

| Question | Answer |
| --- | --- |
| What is the interest? | Giving business clients a research assistant that answers from a curated library of published sector sources, with citations they can check |
| Whose interest? | Ours (a commercial research service); our clients' (efficient research); the public's interest in access to published information |
| Is it lawful and clearly stated? | Yes. Indexing published material for research is a lawful activity, subject to copyright and the text-and-data-mining rules, which we apply separately (§5) |
| Is the personal data the point? | No. People appear because they wrote or are named in the sources. We do not collect data about people as such and offer no search for individuals |

## 3. Necessity test

- **Could we do it without the personal data?** Not without harming the purpose. A citation needs the author; a sector report without the names of the companies' leaders loses meaning. Removing names from every source would also alter publishers' text.
- **Less intrusive ways.** We keep only what the source published. We do not enrich it, combine it into profiles, or add data from other sources. Answers show short excerpts with a link to the publisher, not full documents. Downloads are limited to files flagged `downloadable` on their licence basis.
- **Volume.** The library is a curated set of a few hundred documents and a small number of sites per client package (Phase 1a: about 150 documents across three workspaces), not a general web index.

## 4. Balancing test

| Factor | Assessment |
| --- | --- |
| Nature of the data | Professional information already published by the person, their employer or a publisher. Special categories are not sought |
| Reasonable expectations | People who publish reports or are quoted in trade press expect that their words are read, quoted and cited by researchers. They do not expect to be profiled. Our use matches the first and excludes the second |
| Impact | Low in most cases. The main harm is an inaccurate or out-of-context answer about a named person (DPIA R1), which citations and the "verify against cited sources" notice mitigate |
| Vulnerable people | Not targeted. Sources are business material |
| Power balance | People in the corpus have no relationship with us; that is why the objection route and the public notice matter |
| Scale | Moderate and curated (§3) |

## 5. Safeguards

| Safeguard | Status on Oct 21, 2026 |
| --- | --- |
| Source register with publisher, canonical link, fetch date, licence basis and review date | Built (Phase 0); approval states and licence file from Phase 1b (P1b-01) |
| Licence review before ingestion; written permission or exclusion where in doubt | Process rule; approval step in the console from Phase 1b (P1b-01, P1b-05) |
| robots.txt (RFC 9309) honoured, including crawl delay | Built in the crawler today (`app.content.crawler`) |
| EU TDM opt-out honoured: a reserving `/.well-known/tdmrep.json`, or a `tdm-reservation: 1` header or meta tag, stops the crawl | Built today |
| Pages marked `noai`, `noindex` or `none` (meta robots or `X-Robots-Tag`) skipped | Built today |
| Per-site allow decisions, scope rules, scheduled re-crawl, removed pages withdrawn | From Phase 1b (P1b-04) |
| Special-category filter at crawl time (path patterns, reviewer whitelist) | From Phase 1b (P1b-04) |
| Three-way special-category rule for every file: made public by the person (Art. 9(2)(e)) accepted; revealed by others reviewed and removed or redacted unless a clear basis exists; non-public refused (owner decision Oct 22, 2026; architecture §15.5; counsel to confirm) | Process rule; reviewer check from Phase 1b (P1b-01, P1b-05) |
| Citations and short excerpts, no in-app full-document viewer | Built |
| No profiling of individuals; terms forbid it | Built (no person search); terms in `terms-of-service.md` |
| Objection and erasure requests handled within 30 days: remove the document or ingest a redacted copy; record the decision | Process; manual withdrawal today, full cascade from Phase 1b (P1b-03) |
| Takedown within 10 working days of a request, immediately for licence breaches we find ourselves | SLA timer and queue from Phase 1b (P1b-03); handled manually until then |
| Public privacy notice with an Art. 14 section and a takedown contact | Drafted (`privacy-notice.md`); to publish before the first client launch |

## 6. Transparency: Art. 14(5)(b)

We do not obtain the data from the people concerned, so Art. 14 applies. Writing to each person named in each source would involve disproportionate effort: the names are spread across hundreds of documents, we hold no contact details, and finding them would mean collecting more personal data than we hold now. Art. 14(5)(b) allows us to rely on that, provided we take appropriate measures to protect the people's rights, "including making the information publicly available".

Our measures:

- the public privacy notice (`privacy-notice.md`, section "People named in our sources"), describing the kinds of sources, purposes, legal basis, retention, recipients and rights, and the takedown contact security@myceliumgastronomy.com;
- the safeguards in §5, especially the objection route and the absence of profiling;
- this assessment, kept on file as the record of the disproportionate-effort decision.

Where we write our own analysis about a named, identifiable person in a way they would not expect, we consider informing them directly.

## 7. Conclusion and sign-off

With the safeguards in §5, our legitimate interest in indexing published sources for business research is not overridden by the interests or rights of the people named in them. The conclusion depends on two Phase 1b items for crawled content (P1b-03, P1b-04); until they ship, new sites are added only after a manual check of their pages by the content reviewer.

| | Name | Date |
| --- | --- | --- |
| Owner | [ ] | [ ] |
| DPO or privacy contact | privacyanddata@myceliumgastronomy.com | [ ] |
| Counsel reviewed | [ ] | [ ] |

## 8. Review

Review by [date], and at once when: we add a new kind of source (for example social media or forums); a crawl covers sites about private individuals; a person search or alerting feature is planned (Phase 2 and later); a complaint or regulator enquiry arrives.
