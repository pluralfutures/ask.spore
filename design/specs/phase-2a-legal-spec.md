# Phase 2A-Legal Spec — Legal Links in the Page Footer

Oct 26, 2026 · Status: **Proposed, for owner approval** · Target duration: 1–2 days · Part of Phase 2A (owner, Oct 26, 2026); built after P2A-11 (static trust and disclosure files), before the release item P2A-13

Source: the owner's decisions of Oct 26, 2026 (add as Phase 2A-Legal; a link at the bottom of each user-accessible page), the compliance guide (transparency, GDPR Arts. 12–14, EU AI Act Art. 50), `design/compliance/privacy-notice.md`, `ai-transparency-note.md`, `terms-of-service.md`, `trust-page.md` (publishing mechanism), `ux-refresh-spec.md` (binding list items 1 and 2) and `home-page-spec.md`.

## Goal

A signed-in user, tenant admin or end user, can read the three minimum notices at any time, not only at the consent gate: the **Privacy Notice**, the **AI Transparency Note** and the **Terms**. Today the privacy notice is shown at the gate and then not again, and the other two have no in-app place.

Exit criteria (all must hold):

- Every page that shows the app shell, signed in, ends with a footer carrying the three links (L1).
- Each link opens its document from a static file served by Caddy, with no API call, no cookie and no tenant or user identifier in the request (L2).
- The footer is absent where the existing contract says the page shows no links (the consent gate), and the sign-in page carries the privacy-notice link the draft already requires (L1).
- A link whose document is not yet published is not shown (L2, flag), so the build can ship before counsel signs the texts.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- **Acceptance of the Terms by each user.** The gate keeps recording acceptance of the use and privacy notice only (consent v2). Binding users to the Terms directly is a consent v3 and counsel's call (backlog).
- **Writing or changing the legal texts.** The owner and counsel finalise the three drafts; this phase only serves them.
- Trust page, security disclosure, sub-processor list, DPA, cookie notice, help centre, status page (Phase 2 items, owner documents). The footer may link the sub-processor list only through the privacy notice's own text.
- Per-tenant legal documents, per-tenant footer text, translations, a document version history page.
- Any new tracking, analytics, cookie or third-party request. The footer is three plain links.
- Any change to the AI notice strip (it stays the first element of every page), to prompts, models, retrieval, retention or the consent gate.

## Work items

Build in this order. Every change keeps the CLAUDE.md rules and adds a test. Item IDs go in commit messages.

**P2A-L1 Footer component and placement.** `components/AppFooter.tsx`, rendered by `Shell` after `<main>` so every page that uses the shell gets it once (the signed-in pages, the operator and content consoles included: staff are users too). It is a `<footer>` landmark (`contentinfo`) holding a `<nav aria-label="Legal">` with three links in this order and with these words (new copy, owner to approve, open item 1):

| Link text | Document |
| --- | --- |
| Privacy notice | `privacy-notice.md` |
| AI transparency | `ai-transparency-note.md` |
| Terms | `terms-of-service.md` (user-facing form, open item 2) |

Placement rules:

- The page's `<main>` keeps `flex-1`, so the footer sits at the bottom of the viewport on short pages and after the content on long ones. On pages with the conversation rail (UX-24), the footer is below the rail and the page, not inside the scrolling conversation, so it never covers the composer.
- **Not shown on the consent gate** (`mustAccept`): the gate "shows no links at all" (UX-03 contract) and the notice is on the page in full. It is shown on the sign-in page, which has no shell nav: there it carries at least the privacy-notice link (privacy notice draft, finalise step 5), and the other two as above.
- The AI notice stays the first element in `body`. The skip link, banner and `<main>` order is unchanged; the footer adds no focus trap and no new heading level 1.
- Style: the existing small neutral text style (`text-ui`, muted), the `max-w-[70rem]` container of the top bar, 4.5:1 contrast in light and dark, visible focus ring, links at least 24 px high on touch (WCAG 2.2 target size).

Tests (web): a render test per route listed in `App.test.tsx` asserts one `contentinfo` landmark, the three links in order with their exact text, and no footer on the consent gate; the AI notice is still the first element in `body`; the footer is after `<main>` in the DOM; an axe pass on one page with the footer (UX-23 baseline unchanged, no new violations).

**P2A-L2 Static documents and the publish flag.** The three documents are static HTML files served by Caddy beside the trust page, built the same way as `security-disclosure.html` and the trust page (P2A-11): plain HTML rendered by the owner from the final text, no inline script or style, no external resource, own CSS file under the existing content security policy.

| Route | File | Flag |
| --- | --- | --- |
| `/legal/privacy` | `apps/web/public/legal/privacy.html` | `ASKSPORE_LEGAL_PRIVACY` |
| `/legal/ai` | `apps/web/public/legal/ai.html` | `ASKSPORE_LEGAL_AI` |
| `/legal/terms` | `apps/web/public/legal/terms.html` | `ASKSPORE_LEGAL_TERMS` |

Each flag is `published` or `unpublished` (default `unpublished`) in `infra/.env`, as `ASKSPORE_TRUST_PAGE` is; unpublished answers 404 at Caddy. The footer shows only the links whose flag is `published`: the web build reads the flags through the same build-time or config mechanism P2A-11 used for the trust page, and **no API endpoint is added** (an API call would be a request carrying a session). If no document is published, no footer is rendered. Links open in a new tab (`target="_blank"`, `rel="noopener"`) so a user in the middle of a conversation does not lose their place. The routes need no sign-in (the privacy notice must be public anyway, Art. 12 and the draft's step 5), so a link in an email or at the sign-in page works.

Each document carries its version and date in the first lines. The file is replaced by the owner on a new version; the consent gate's `config/consent/v*.md` is a separate, shorter text and is not generated from these (open item 3).

Tests: Caddy config test (the existing style): each route answers 200 when published and 404 when not; no `Set-Cookie`, the same security headers as the trust page; the page contains no `<script>` and no external URL. Web test: a link is rendered only for a published flag; with none, no footer.

**P2A-L3 Privacy and logging guarantees.** The footer and its routes must not become a tracking path.

- The links carry no query string, fragment or identifier (no tenant, user, workspace or session value), asserted by test on every rendered `href`.
- Caddy's access log for these routes follows the existing allow-listed fields (path, status, time; no cookie or `Authorization` header). No request-body or header logging is added.
- No audit event is written for reading a legal document (it would record a user's reading as personal data for no control gain). The consent acceptance remains the only legal event audited.

Tests: `href` assertion above; a Caddy log-format test that the fields are the allow-listed ones for `/legal/*`.

**P2A-L4 Documentation.** Update the design where the code now matches it: `ux-refresh-spec.md` binding list (the footer is a new element; the AI notice rule is unchanged), `privacy-notice.md` and `ai-transparency-note.md` finalise lists (step "link from the in-app AI notice and the consent gate" is met by the footer; the gate itself still shows the full notice), `terms-of-service.md` (note which form is served), the architecture's UI section, and `phase-2a-release-runbook.md` (the three flags and the order: publish a document only after counsel signs it).

## Open items for the owner

1. **Link wording** ("Privacy notice", "AI transparency", "Terms"). New user-facing copy, so it needs your approval or edits before build.
2. **Which "Terms" users read.** `terms-of-service.md` is the client MSA, with placeholders for price, liability cap and the client's name; it cannot be served to every user as it stands. Options: (a) serve a user-facing "Terms of use" derived from it (acceptable use, output disclaimer, content ownership), the MSA staying a signed contract; (b) serve the MSA with commercial terms removed. **Recommended: (a)**, written with counsel; until it exists, leave `ASKSPORE_LEGAL_TERMS=unpublished` and the footer shows two links.
3. **One source for the privacy notice.** The gate's text (`config/consent/v2.md`) and the public privacy notice can drift. Recommended: keep both, and add a test or release-runbook check that the version string in the gate and in `privacy.html` match.
4. **Footer on the consent gate.** Kept off by the UX-03 contract. If you want it there too, the gate already contains the full notice; the other two would need links, which is a change to that contract.

## Decisions to record in the findings file when built

The final link wording, the chosen "Terms" form, the flags' values on the Instance, and the date counsel signed each published text.
