# Phase 2A-Legal Spec — Legal Link in the Page Footer, Terms of Use, Sign-in Email and Repeat Sign-in

Oct 26, 2026 · Status: **Owner decisions of Oct 26, 2026 taken (table below); P2A-L1 to L5 built; L6 decided, waits on its Authentik probe** · Target duration: L1–L4 1–2 days, L5 half a day, L6 2–3 days · Part of Phase 2A; built after P2A-11 (static trust and disclosure files), before the release item P2A-13

Source: the owner's messages of Oct 26, 2026, the compliance guide (transparency, GDPR Arts. 12–14, EU AI Act Art. 50; "MFA for tenant admins" and the Oct 22 addendum on the admin second factor), `design/compliance/privacy-notice.md`, `ai-transparency-note.md`, `terms-of-service.md`, `terms-of-use.md` (new), `trust-page.md` (publishing mechanism), `ux-refresh-spec.md` (binding list items 1 and 2), `infra/authentik/` (template and blueprint) and `home-page-spec.md`.

## Owner decisions of Oct 26, 2026

| # | Decision |
| --- | --- |
| 1 | The footer link is worded **"Legal"**: one link at the bottom of every page, opening a page that lists the three documents (privacy notice, AI transparency note, Terms of Use). |
| 2 | Users read a short **Terms of Use**, written for this purpose (`design/compliance/terms-of-use.md`, drafted Oct 26, 2026 from the MSA's clauses; counsel to review). The client MSA (`terms-of-service.md`) stays a signed contract and is not shown to users. |
| 3 | The footer **also shows on the consent gate**. This changes the UX-03 contract ("the consent page shows no links at all") and binding list item 1 of `ux-refresh-spec.md`, which this phase amends (L4). |
| 4 | Go ahead and build. |
| 5 | Add two sign-in items (L5, L6) to this spec: a shorter sign-in email, and no emailed link on repeat sign-ins for a user who has an authenticator app. |
| 6 | **L6 follows the recommendation: option C (trusted browser: link and code the first time on a browser, then email and code), and option B (admins keep link and code; email and code only for enrolled non-admins) if the probe shows C is not cheap.** Option A (one factor for admins) is not taken. |
| 7 | **Lost phone: operator-only reset.** No "use an emailed link instead" on the code page. |
| 8 | The new sign-in email wording of L5 is approved as written. |

## Goal

A signed-in user, tenant admin or end user, can read the three minimum notices at any time, not only at the consent gate. The sign-in email is short and clean. A user who has set up an authenticator app signs in with their email address and the app's code.

Exit criteria (all must hold):

- Every page that shows the app shell, signed in or not, the consent gate included, ends with a footer carrying the "Legal" link (L1).
- `/legal` and the three documents are static files served by Caddy, with no API call, no cookie and no tenant or user identifier in the request (L2).
- The sign-in email contains only the short text of L5 and one link, and no template comment.
- Repeat sign-in for an enrolled user follows L6 as the owner decides it.

## Not in this phase

Binding. Record ideas in `backlog.md`.

- **Acceptance of the Terms of Use by each user.** The gate keeps recording acceptance of the use and privacy notice only (consent v2). Binding users to the Terms of Use directly is a consent v3 and counsel's call (backlog).
- **Finalising the legal texts.** The owner and counsel finalise the three drafts; this phase only serves them.
- Trust page, security disclosure, sub-processor list, DPA, cookie notice, help centre, status page (Phase 2 items, owner documents).
- Per-tenant legal documents, per-tenant footer text, translations, a document version history page.
- Any new tracking, analytics, cookie or third-party request. The footer is one plain link.
- Any change to the AI notice strip (it stays the first element of every page), to prompts, models, retrieval, retention or the consent gate's content.
- Passkeys and hardware keys (backlog, ideas 3.4). L6 stays with TOTP.

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

### Sign-in changes (added Oct 26, 2026)

**P2A-L5 A short sign-in email. Built Oct 26, 2026 (copy approved, decision 8).** Today the email shows, above or instead of its content, the template's own comment. Cause (found by reading `infra/authentik/templates/ask-spore-sign-in.html`): the file documents itself in a multi-line `{# … #}` comment, and Django's `{# #}` is single-line only, so Authentik prints the whole comment as text. It also contains `{{ url }}`, which the comment is meant to forbid linking to and which therefore expands to Authentik's own flow URL with the live `?flow_token=` in the query string. That is the exact thing the comment says must never reach a mail. The fix is in the file, not in the copy:

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

**P2A-L6 Repeat sign-in with an authenticator app: email address, then code, no emailed link. Decided Oct 26, 2026 (decisions 6 and 7); not built: the probe comes first.** Today every sign-in is: email address → emailed link → (tenant admins only) authenticator code → signed in. The owner wants a user who has set up an authenticator app to enter their email address and then the code, with no link.

How it would work: the flow `ask-spore-sign-in-link` gets a branch after the identification stage. If the identified user has a TOTP device, skip the email stage and go to the code stage, then login. If not, today's path: email link, and for tenant admins the setup of the app. Authentik does this with a policy on the email stage's binding (skip it when `ak_user_has_authenticator(pending_user, "totp")`) and the code stage placed before login (`not_configured_action: configure` stays for admins who have no device). The API relays the flow (`AuthentikProvider.send_sign_in_link`, `redeem_sign_in_link`, `answer_mfa`): a new request shape is needed, "email, then code" without the link redemption, and the sign-in page needs a code step after the email step. **A probe is the first task, as P2A-00 was**: confirm on the pinned Authentik version that the identification stage exposes the pending user to the policy without a leak, that the code stage works with no email stage before it, and what the unauthenticated response looks like for an unknown address, an enrolled address and an unenrolled address.

**Decisions this needs from the owner (decisions 6 and 7).** This change has a security consequence that the compliance guide's wording makes the owner's call, not ours:

- *It turns a two-factor sign-in into a one-factor sign-in for tenant admins.* Today an admin proves control of their inbox (the link) **and** of their phone (the code). With the owner's proposal an email address, which is not secret, plus the code is the only check. The compliance guide says "MFA for … tenant admins" (§ access control; Oct 22 addendum), and SOC 2 CC6.1 is mapped to it. One factor plus a non-secret identifier is not MFA in the usual audit reading.
- *It reveals which addresses have an app.* Unknown and unenrolled addresses would see the "check your email" page, enrolled addresses the code page. That is an account-enumeration signal for exactly the accounts worth attacking. The identification stage's "pretend user exists" protection no longer hides it. Mitigations to build whichever option is chosen: a rate limit and lockout on code attempts per address and per network, the same code page for an unknown address (it rejects every code), and code replay refused.
- *Lost phone.* With no link, a user who has lost the device has no self-service path. Today the link plus operator reset covers it. The fall-back needs deciding: a visible "Use an emailed link instead" on the code page (which keeps the link as the fallback factor), or an operator-only reset.

Options for the owner:

| Option | What the user does | Factors for a tenant admin |
| --- | --- | --- |
| A. As asked | Email → code, for every enrolled user | One (code). Needs the compliance guide's MFA line changed for admins and counsel's agreement |
| B. **Recommended** | Email → code for enrolled **non-admin** users only; tenant admins keep link + code | Admins stay at two. Non-admins who enrol are a voluntary extra, not a control. Today only admins can enrol, so this needs an opt-in enrolment for others and is the larger build |
| C. Trusted browser | Link + code the first time on a browser (and at most every 30 days); email → code afterwards on that browser | Two (browser holds a device-bound trusted cookie, plus the code). Probe whether Authentik supports it without a custom stage; if not, a small API change |
| D. Keep as is | No change | Two |

Recommendation: **C if the probe shows it is cheap, else B.** C gives the owner the request (no link on the usual device) without dropping the admin to one factor. If the owner chooses A knowingly, record the decision and the compliance-guide amendment in the same PR, and ship the rate limit, lockout and "same page for unknown address" with it.

Tests (for the chosen option): an enrolled user signs in with email and code and never triggers an email send (fake provider counts sends); an unenrolled user still gets the link; the response for an unknown address cannot be told from an enrolled one (same status, same body shape, comparable timing within a stated bound); five wrong codes lock the address for a stated period with the audit event `auth.lockout` and no code in the log; a replayed code is refused; the admin MFA negative test still holds (an admin without a device cannot reach the app).

## Open items for the owner

1. **Keeping the gate's text and the public privacy notice in step.** The gate shows `config/consent/v2.md`; `/legal/privacy` is generated from `privacy-notice.md`. Recommended: the release-runbook check that the version strings match (added to the runbook, Oct 26, 2026); confirm.
2. **Operator reset of an authenticator (decision 7).** The operator console has no action for it today. L6 adds one: an operator removes a user's TOTP device and trusted-browser marks through the Authentik API, audited (`auth.mfa_reset`, no code in the log), after the user asks through support and the operator has checked who they are (the support checklist, `staff-access-checklist.md`, gets a line). Confirm the operator may do this for tenant admins as well as users.

## L6 build order (decided)

1. **Probe** on the pinned Authentik version, written to `phase-2a-findings.md`: (a) whether a "remember this browser" mechanism exists that is bound to the browser and expires (the authenticator validate stage's `last_auth_threshold` is the candidate), without a custom stage; (b) whether the email stage can be skipped by a policy on the identified user's TOTP device; (c) the unauthenticated responses for an unknown, an unenrolled and an enrolled address, and whether they can be made the same.
2. **If (a) and (b) hold: option C.** Flow: identification; if the browser is trusted and the user has a device → code → login; else email link → (admins without a device: setup) → code → login. The trust lasts at most 30 days and is marked on sign-in, not renewed by use, and is dropped when the user's device is reset or the user is disabled.
3. **Otherwise option B**, plus an opt-in enrolment for non-admins, as specified in the options table.
4. Operator reset (open item 2), lockout, the same response for every address, and the tests listed under L6.

## Decisions to record in the findings file when built

The flag's value on the Instance and the date counsel signed each published text; the L6 option chosen, the probe results and, for option A, the compliance-guide amendment.
