# Phase 2A-Legal Spec — Legal Link in the Page Footer, Terms of Use and Sign-in Email

Oct 26, 2026 · Status: **P2A-L1 to L5 built and merged (PR 76; L5 kept after a revert, below); the texts approved by counsel; waits on `ASKSPORE_LEGAL=published` on the Instance** · Target duration: 1–2 days · Part of Phase 2A; built after P2A-11 (static trust and disclosure files), before the release item P2A-13

Source: the owner's messages of Oct 26, 2026, the compliance guide (transparency, GDPR Arts. 12–14, EU AI Act Art. 50; "MFA for tenant admins" and the Oct 22 addendum on the admin second factor), `design/compliance/privacy-notice.md`, `ai-transparency-note.md`, `terms-of-service.md`, `terms-of-use.md` (new), `infra/authentik/templates/` (the sign-in email), `trust-page.md` (publishing mechanism), `ux-refresh-spec.md` (binding list items 1 and 2) and `home-page-spec.md`.

## Owner decisions of Oct 26, 2026

| # | Decision |
| --- | --- |
| 1 | The footer link is worded **"Legal"**: one link at the bottom of every page, opening a page that lists the three documents (privacy notice, AI transparency note, Terms of Use). |
| 2 | Users read a short **Terms of Use**, written for this purpose (`design/compliance/terms-of-use.md`, drafted Oct 26, 2026 from the MSA's clauses; counsel to review). The client MSA (`terms-of-service.md`) stays a signed contract and is not shown to users. |
| 3 | The footer **also shows on the consent gate**. This changes the UX-03 contract ("the consent page shows no links at all") and binding list item 1 of `ux-refresh-spec.md`, which this phase amends (L4). |
| 4 | Go ahead and build. |
| 5 | A shorter sign-in email (L5); the new wording is approved as written. |

## Goal

A signed-in user, tenant admin or end user, can read the three minimum notices at any time, not only at the consent gate. The sign-in email is short and clean.

Exit criteria (all must hold):

- Every page that shows the app shell, signed in or not, the consent gate included, ends with a footer carrying the "Legal" link (L1).
- `/legal` and the three documents are static files served by Caddy, with no API call, no cookie and no tenant or user identifier in the request (L2).
- The sign-in email contains only the short text of L5 and one link, and no template comment.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- **Acceptance of the Terms of Use by each user.** The gate keeps recording acceptance of the use and privacy notice only (consent v2). Binding users to the Terms of Use directly is a consent v3 and counsel's call (backlog).
- **Finalising the legal texts.** The owner and counsel finalise the three drafts; this phase only serves them.
- Trust page, security disclosure, sub-processor list, DPA, cookie notice, help centre, status page (Phase 2 items, owner documents).
- Per-tenant legal documents, per-tenant footer text, translations, a document version history page.
- Any new tracking, analytics, cookie or third-party request. The footer is one plain link.
- Any change to the AI notice strip (it stays the first element of every page), to prompts, models, retrieval, retention or the consent gate's content.

## Work items

Build in this order. Every change keeps the CLAUDE.md rules and adds a test. Item IDs go in commit messages.

**P2A-L1 Footer component and placement.** `components/AppFooter.tsx`, rendered by `Shell` after `<main>`, so every page that uses the shell gets it once: sign-in, loading, signed-in pages, the consent gate, the operator and content consoles. It is a `<footer>` landmark (`contentinfo`) holding `<nav aria-label="Legal">` with one link, "Legal", to `/legal`. The link opens in a new tab (`target="_blank"`, `rel="noopener"`, a visually hidden "(opens in a new tab)") so a user in the middle of a conversation or at the gate does not lose their place.

- `<main>` keeps `flex-1`, so the footer sits at the bottom of the viewport on short pages and after the content on long ones. Pages with the conversation rail (UX-24) keep the composer visible; the footer is below the page, not over it.
- The AI notice stays the first element in `body`. The skip link, banner and `<main>` order are unchanged; the footer adds no focus trap and no heading.
- Style: the muted `text-ui` style, the top bar's `max-w-[70rem]` container, 4.5:1 contrast, the global focus ring, a target at least 24 px high.
- The gate's own test "no links" becomes "the only link is the footer's Legal link" (decision 3).

Tests: web render test and Playwright: one `contentinfo` landmark with one link "Legal" on the sign-in page, a signed-in page, a rail page and the gate; the AI notice is still the first element in `body`; the footer follows `<main>`; the gate still has no other link; an axe pass with no new violations.

**P2A-L2 Static documents, the index and the publish flag.** Four static files in the web build under `public/legal/`, served by Caddy as plain files beside the trust page: `index.html` (`/legal`: the list of the three documents and the privacy contact), `privacy.html` (`/legal/privacy`), `ai.html` (`/legal/ai`) and `terms.html` (`/legal/terms`). The three documents are **generated** from `design/compliance/privacy-notice.md`, `ai-transparency-note.md` and `terms-of-use.md` (the text below each file's "Plain text below the line" marker) by `apps/web/scripts/render-legal.mjs`, so the source stays the one place to edit; the script supports only the markdown those files use. `--check` fails if a page is stale (run by a unit test); `--final` refuses a source that still has a `[placeholder]` or a DRAFT marker and is a release-runbook step before publishing.

One deploy-time flag, `ASKSPORE_LEGAL` (`published` or the default `unpublished`, in `infra/.env`, passed by Compose, as `ASKSPORE_TRUST_PAGE` is), controls all four routes: unpublished answers 404 at Caddy, any other value stops Caddy at start. The footer link is always rendered (the web build cannot read a Caddy flag); the release runbook therefore publishes the flag **before** the Instance serves users. The files' own `.html` names are 404. The routes need no sign-in, no cookie and no API call (the privacy notice must be public anyway, Art. 12).

Tests: Playwright (the dev server mirrors the routes, as for P2A-11): `/legal` and the three documents answer 200 without an API call or a script; the `.html` names are 404; the index links to the three. Unit test: generated pages are current. Release runbook: the flag and the `--final` check.

**P2A-L3 No tracking path.** The link carries no query string, fragment or identifier (asserted on its `href`). Caddy writes no access log (a `log` directive is never added, Caddyfile header), so nothing new is logged; no audit event is written for reading a legal document.

**P2A-L4 Documentation.** Amend `ux-refresh-spec.md` (binding item 1: the gate shows the footer's Legal link and no other navigation; the UX-03 contract test), `privacy-notice.md` and `ai-transparency-note.md` finalise lists (the in-app link is met by the footer), `terms-of-service.md` (note: users read `terms-of-use.md`), `infra/caddy/README.md`, the architecture's UI section, and `phase-2a-release-runbook.md` (the flag, the `--final` check, publish only texts counsel signed).

### Sign-in email (added Oct 26, 2026)

**P2A-L5 A short sign-in email. Built Oct 26, 2026 (copy approved, decision 5).** Today the email shows, above or instead of its content, the template's own comment. Cause (found by reading `infra/authentik/templates/ask-spore-sign-in.html`): the file documents itself in a multi-line `{# … #}` comment, and Django's `{# #}` is single-line only, so Authentik prints the whole comment as text. It also contains `{{ url }}`, which the comment is meant to forbid linking to and which therefore expands to Authentik's own flow URL with the live `?flow_token=` in the query string. That is the exact thing the comment says must never reach a mail. The fix is in the file, not in the copy:

- Replace the comment with `{% comment %}…{% endcomment %}` (multi-line, never rendered, its `{{ url }}` not evaluated) and write the explanation without the template variable.
- New copy (new user-facing text, owner to approve; subject stays "Sign in to SporeBot"):

  > **Sign in to SporeBot**
  >
  > [Sign in] (the one link, a button-style link to `https://askspore.myceliumgastronomy.com/auth/finish#token=…`)
  >
  > The link works once and expires in 15 minutes. If you didn't ask for it, you can ignore this email.

  It drops "in the browser where you asked for it" from the email: the landing page already says what to do when opened in another browser. If the link opens in a different browser, `/auth/finish` shows the existing message.
- The email carries nothing but the recipient's own address and the link (compliance addendum, "Platform mail"): no tenant, user, notice or job identifier.

Tests (API or infra): a test reads the template and asserts it has no `{#`, that every `{{ … }}` outside a `{% comment %}` block is `{{ token }}`, and that it holds exactly one `href`; a render with Django's template engine (a dev-only dependency, or `jinja2`-free regex if the engine is not already available) asserts the output contains neither `flow_token` nor `{#` nor `authentik-server`. `infra/authentik/README.md` ("Email template") updated.

## Open items for the owner

None open. Settled Oct 26, 2026: the version-match check is built (below) and stays.

**Version-match check (built).** `node scripts/render-legal.mjs --final` fails unless the privacy notice's "Version N," equals the version line of the consent notice the gate shows (`config/consent/<[consent] version>.md`). It is a release-runbook step. It currently fails by design: the privacy notice still says `[version]`, and `v2.md` ends "Version 1, Oct 22, 2026" although it is the v2 file. A released consent version is never edited, so the owner decides which number the public notice carries when it is finalised (the next consent version is the natural point to align them).

## Set aside (Oct 26, 2026)

**P2A-L6, no emailed link on repeat sign-ins for a user with an authenticator app, was specified and probed and then withdrawn by the owner for now.** It was never built, and its spec text was removed. The Authentik probe is written up on the unmerged branch `claude/p2a-l6-probe` (`phase-2a-findings.md` section 7, commit `16fd357`; recommendation: the trusted-browser option, with a mandatory guard policy against Authentik failing open). It can be taken up again as a new spec item. The sign-in flow and the Authentik blueprint are unchanged from before PR 76; only the email template (L5) differs.

## Decisions to record in the findings file when built

The flag's value on the Instance and the date counsel signed each published text.
