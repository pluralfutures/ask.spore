# Visual audit of the web app (apps/web), Oct 23, 2026

Look and feel only: no branding, no change to behaviour, copy or flow. Companion documents: [design-direction.md](design-direction.md) (the proposed look) and [../specs/ux-refresh-spec.md](../specs/ux-refresh-spec.md) (the draft rebuild plan). Mockups of three screens (chat with citations, start panel, tenant admin), each beside its current screenshot, are on a design canvas: https://claude.ai/artifact/3spU4UTTXALVNbfdaFiRJE (private until its owner shares it).

## How the screenshots were made

- The app was run with the Vite dev server against a fake of `/api/v1` installed with Playwright `page.route`, the same approach as `apps/web/e2e/fakeApi.ts`. No API, RAGFlow, Postgres, Redis or Authentik was started. All data is synthetic ("Synthetic …" publishers, `example.org` addresses).
- Every route and key state was captured full-page at **1440 px** (desktop, 1× pixel ratio) and **390 px** (phone, 2× pixel ratio). The PNGs are colour-quantised to keep the repo small; they are faithful for layout and colour.
- Stress fixtures: a ~400-word structured answer with 14 citations, a 170-character source title, a 95-character publisher, a 75-character email address, long conversation titles, a superseded and a withdrawn citation, a citation with no date or page, and empty lists.
- An automated accessibility pass ran axe-core 4.10 (WCAG 2 A/AA plus best practice) on every desktop state, and a keyboard pass pressed Tab three times on each.
- The script was throwaway and is not committed (CLAUDE.md: no app-code changes in this session). It can be rebuilt from the scenario list below. Spec item UX-01 turns it into a committed visual-regression suite.

File names are `design/ux/screenshots/<scenario>-<desktop|phone>.png`.

## Cross-cutting findings

These cause most of what the per-screen notes repeat, so they come first.

1. **Borders are near-black everywhere.** Components use a bare `border` class. In Tailwind v4 a bare border defaults to `currentColor` (v3 used gray-200), so every card, table, input and textarea gets a 1 px slate-900 outline. It is the single largest reason the app looks unfinished. The same cause hides the focus ring (finding 6).
2. **No type system, and no defined font.** The page inherits Tailwind's `font-sans` (the OS UI font: Segoe UI, SF, Roboto or whatever Linux has), so the app looks different on every client machine. Sizes are ad hoc: page titles use `text-xl` on some pages and `text-lg` in chat; section headings are `font-semibold` at body size, so a section title, a table header and a field label all look the same. In answers, **Markdown headings render as plain body text**: `prose-sm` is used but the typography plugin is not installed and preflight resets `h2`, so "Summary" and "Market drivers" read as ordinary sentences (09-chat-long-answer…).
3. **There is no app shell or navigation.** Each page links back with an underlined "← Conversations". There is no persistent header, no indication of which tenant or workspace you are in, and no sign-out except a bare underlined button that appears *below* the content in OIDC mode (App.tsx). Administration and Operator console are underlined links whose position shifts depending on which ones are shown (06b).
4. **Phone layouts overflow horizontally.** Pages use `mx-auto max-w-*` on a flex-column child without `w-full`, so their width becomes the content's max-content width. At 390 px, 12 of the 58 states grow wider than the screen: conversation list 768 px, tenant admin 860–927 px, operator users 875 px, content sites 627 px, register 542 px, takedowns 483 px, start panel with long model names 470 px, files 416 px. Tables have no scroll container and no stacked layout.
5. **No shared controls.** There are at least five button styles: filled slate-900, grey disabled, outlined (content console), underlined text links acting as buttons ("Deactivate", "Remove", "Resend invitation", "Close"), and emoji buttons (👍 👎). Inputs come in three paddings (`px-2 py-1`, `px-2`, `border px-1`), and some selects have no border at all (admin table, workspace defaults). Disabled primary buttons are 50% opacity, white on mid-grey (about 2.6:1), and look like a different kind of button rather than an unavailable one.
6. **Focus is barely visible.** Keyboard focus is the browser default outline, a thin dark ring, against near-black borders. On the textarea it is indistinguishable from the border (focus-07-start-panel-single). Nothing sets `focus-visible` styles.
7. **Colour carries meaning inconsistently.** Amber is used for the AI notice, the external-model note, the spend-cap notice, partial and truncated answers, the "possible replacement" badge, superseded and withdrawn citations, and the General knowledge mode badge. Red is used for errors, the Delete links, the "Unsupported answer" badge and takedown status. Indigo is used for one badge (Reasoning on), and sky blue for citation markers and the selected citation. With no accent colour, links are black underlined text, so primary navigation, inline links and button-links all look alike.
8. **Status text is raw machine values.** `active`, `invited`, `deactivated`, `corpus_only`, `general_knowledge`, `eu-standard`, `external_spend_50`, `workspace_instructions_name_match`, `parse_error`, `content_editor, content_reviewer` are shown as-is. There are no status badges, so tables need reading rather than scanning.
9. **Loading, empty and error states are bare text.** "Loading…" sits at the top-left of a blank page, with no skeleton and no landmark (axe: page-has-heading-one and region on every loading state). "No conversations yet." has no call to action. Errors are a red sentence with no retry. The chat's "Searching your research package…" is plain grey text with no progress indication.
10. **Landmarks and headings.** The AI notice and the sign-in forms sit outside any landmark on 58 of 58 states (axe `region`). Sign-in has no `<main>` (`landmark-one-main`). The start panel, its loading and error states, and the consent error have no `h1`. Five tables have an empty action-column header (`empty-table-header`). Every route has the same document title, "SporeBot" (WCAG 2.4.2).

## Per-screen findings

Each finding is tagged: **T** type hierarchy, **S** spacing, **C** colour, **A** alignment, **K** inconsistent controls, **L** layout and navigation, **M** missing state, **X** accessibility.

### Sign-in (email, SSO choice, link sent, token sign-in, finish page)

![Email sign-in, desktop](screenshots/02-signin-email-desktop.png)

| | |
|---|---|
| ![SSO choice](screenshots/02d-signin-sso-choice-desktop.png) | ![SSO refused, phone](screenshots/02b-signin-email-sso-failed-phone.png) |

- **L** A 236 px form floats near the top-left third of a 1440 px page with nothing else. There is no card, no product context and no explanation of what happens next ("we'll email you a link").
- **T** The product name ("SporeBot", `text-xl font-semibold`) is the only heading and reads as a label, not a page title.
- **K** "Continue" is a full-width filled button, while "Email me a sign-in link instead" is a small underlined link. The SSO button label has no provider mark or icon.
- **C/X** The SSO refusal is red text below the button. It has `role="alert"`, but no icon or container, so it is easy to miss.
- **M** There is no visual confirmation state on "link sent" (02c): no icon and no "use a different address" action.
- **X** No `<main>` landmark and no `h1` on the token form (axe).
- Token sign-in (01, Phase 0 only) and the finish page (03) share the same unstyled stack.

### App loading

![Loading](screenshots/04-app-loading-desktop.png)

- **M** "Loading…" as 14 px text, centred only by `mx-auto` on a paragraph. No spinner, no skeleton, and no `h1` or `main` (axe).

### Consent gate (compliance: content and place are binding, see the spec)

![Consent, first](screenshots/05-consent-first-desktop.png)

| | |
|---|---|
| ![Consent changed](screenshots/05b-consent-changed-desktop.png) | ![Consent, phone](screenshots/05-consent-first-phone.png) |

- **T** Markdown headings in the full notice ("1. What this service is") render as body text, for the same reason as in answers, so a long legal notice has no visible structure. The "In short" bullet list renders without bullets (preflight removes `list-style`).
- **X (serious per axe)** The full notice is a `max-h-[50vh] overflow-y-auto` box with no tab stop of its own (axe `scrollable-region-focusable`). Chromium and Firefox make such a box keyboard-focusable themselves, so it can be scrolled with the keyboard there (confirmed by the UX-02 keyboard test, Oct 24); Safari does not, and the box has no accessible focus treatment. This matters for a consent the user must read. *Corrected Oct 24, 2026: the first version said keyboard users could not scroll it at all.*
- **L** The checkbox and "Accept and continue" sit below a scroll box. On a 900 px screen they are just visible; on phone they are far below the fold, with no sense of how much is left to read.
- **K** The accept button is `px-3 py-1` (about 28 px tall), smaller than the start and ask buttons. When disabled it is grey with low contrast.
- **C** "The notice has changed…" (05b) is amber text with no container, styled like the AI notice above it.
- **M** The error state (05c) is a single red sentence with no retry and no `h1`.

### Conversation list (home)

![Conversations, admin + operator](screenshots/06b-conversations-admin-operator-desktop.png)

| | |
|---|---|
| ![Conversations, phone overflow](screenshots/06-conversations-phone.png) | ![Empty](screenshots/06c-conversations-empty-desktop.png) |

- **L (severe on phone)** The page is 768 px wide at 390 px (finding 4). The long title's truncation forces the width.
- **L** The header row spreads the h1, "Administration", "Operator console" and "New conversation" with `justify-between`, so the links float at arbitrary positions.
- **C** A red underlined "Delete" sits on every row, the most prominent element after the titles. It is a destructive action with equal weight to opening the conversation, and it uses `window.confirm`.
- **T/S** Row titles and "Expires …" meta have weak contrast in size (16 vs 14 px), and rows have 12 px padding. "Files behind each workspace" is a small bold label above a row of underlined links, with no explanation.
- **M** The empty state "No conversations yet." has no call to action or explanation. Loading is bare "Loading…" with the empty bordered list already drawn (06d). The error is red text above an empty bordered box (06e).
- **M** There is no workspace, model or last-activity information per row. Expiry is the only metadata, so the retention indicator is present but not explained.

### Start panel (new conversation)

![Start panel, choices](screenshots/07b-start-panel-choices-desktop.png)

| | |
|---|---|
| ![External model](screenshots/07c-start-panel-external-desktop.png) | ![Single workspace and model](screenshots/07-start-panel-single-desktop.png) |

- **T/L** A `<fieldset>` with a browser-default legend ("New conversation") is the page's only heading; there is no `h1` (axe). The question box, the most important control on the page, sits *below* the settings, has no visible label, and is an 80 px textarea.
- **K** The settings are native selects with black borders, and the Start button is disabled grey until the user types.
- **C** The external-model note is the same amber box as other notes, yet it is the most consequential choice on the page: data leaves the EU.
- **L** With one workspace and one model (the common client case, 07) the panel shows "Workspace: Synthetic Markets" as a sentence and **hides the model entirely**, while still saying "These settings cannot be changed…". The user cannot see which model will answer.
- **X** The reasoning checkbox's "(not available for this model)" is grey 14 px text inside the label (07d).
- **M** There is no hint of what the workspace contains (no link to its files) and no example questions.
- **L (phone)** The page is 470 px wide when a model name is long (07b/07c).

### Chat: streamed answer, citation panel, notes

![Answer with citation open](screenshots/08c-chat-answer-citation-open-desktop.png)

| | |
|---|---|
| ![Searching](screenshots/08-chat-searching-desktop.png) | ![Citation panel on phone](screenshots/08c-chat-answer-citation-open-phone.png) |

![Long answer, 14 citations](screenshots/09-chat-long-answer-many-citations-desktop.png)

![Notes, abstained, unsupported](screenshots/09c-chat-notes-abstain-unsupported-desktop.png)

- **T (severe)** Answer Markdown headings render as body text (cross-cutting 2). Long answers are a wall of 16 px text in a black-bordered box. There is no reading measure; the column is 736 px at most, which is fine, but the line height is the body default.
- **K** Citation markers are 12 px sky-blue chips about 16×16 px (below the 24 px minimum target size, WCAG 2.2 2.5.8). Feedback is two emoji buttons about 35×20 px with no visible text. Their `aria-label`s ("Helpful", "Not helpful") are correct.
- **L (severe on phone)** On phone the citation panel opens *below the composer*. With a one-answer thread that fits on the screen it is still visible (08c phone), but once the thread is longer than a screen the source opens out of view, so tapping a marker appears to do nothing (09 phone; checked by a UX-03 test). *Corrected Oct 24, 2026: the first version said it always opened off-screen.* On desktop the panel is a full-height column whose height grows the page, so with 14 citations the composer is pushed 2,000 px down (09). The selected citation (9) is not scrolled into view.
- **C** The selected citation uses a sky-blue ring, the only use of that colour outside markers.
- **T** In the source card the provenance line (publisher · date · page) wraps awkwardly ("p.\n12"). Long titles are bold at the same size as body text, and the "superseded"/"withdrawn" badges plus an explanatory line in 12 px amber stack above the provenance.
- **A** The conversation header mixes a grey pill (workspace), plain text (model), an indigo pill (Reasoning on), an amber pill (General knowledge) and grey text (Expires), at three heights.
- **M** "Searching your research package…" is plain grey text with no progress indication. "Stop" is an outlined black button indistinguishable from other secondary buttons. There is no "copy answer" or "scroll to latest" action.
- **C** Partial, truncated and failover notes (09c) are 14 px amber or grey lines *outside* the answer card, visually detached from the answer they qualify. "Unsupported answer" is a small red pill inside the card; "Nothing relevant found" is a dashed box. Three answer qualities are shown in three unrelated styles.
- **L** The title stays "New conversation" while the first answer streams, and the header block (back link, title, chips, expiry) takes about 90 px with no separation from the thread.

### Workspace files

![Files](screenshots/10-files-desktop.png)

| | |
|---|---|
| ![Files, phone](screenshots/10-files-phone.png) | ![Files, empty](screenshots/10b-files-empty-desktop.png) |

- **A/S** The table has no cell padding: text touches the cell edges, and dates wrap onto two lines ("15 Feb / 2026") while the title column has spare room. The header sits on the page background, not on the table's white.
- **K** "View at source" and "Download" are both underlined text, and the "(DOCX)" type tag is grey text after the title.
- **X** The action column header is empty (axe).
- **L** "Websites" is a separate list in a different style (dot-separated sentence), with no heading level or explanation.
- **M** The empty state is a single grey sentence, and there is no search or filter (out of scope for Phase 1a, but the layout should leave room for it).

### Tenant admin

![Tenant admin](screenshots/11-tenant-admin-desktop.png)

| | |
|---|---|
| ![Tenant admin, phone (860 px wide)](screenshots/11-tenant-admin-phone.png) | ![Remove confirmation](screenshots/11c-tenant-admin-remove-confirm-desktop.png) |

- **L** All five sections (users, workspaces, retention, sign-in, audit log) are stacked on one 2,000 px page with no in-page navigation or tabs. The operator console's tenant page uses tabs for similar content.
- **A (severe)** The users table has no padding and no row separators. "Last login" wraps to four lines ("19 Oct / 2026 · / sign-in / link"). Action links stack vertically and do not line up with their rows. Role selects have no border and look like plain text with a chevron.
- **K** The invite form sits above the table with labels above unpadded inputs and an unbordered role select. The Invite button is greyed out until both fields are filled, with no hint why.
- **C** "Remove" is an underlined black link, but its confirmation is a red filled button that reflows the row (11c).
- **T** Section titles are 14 px semibold, the same as table headers and field labels. "Workspaces" is a heading outside the cards while "Users" is inside its card.
- **K** "Save defaults" and "Save as new version" sit in different positions, and the character count floats next to the button. "Version history" is a native `<details>` with a black triangle.
- **L** In the sign-in summary, raw config keys (`tenant`, `client_id`, `redirect_uri`) appear in lower-case code style beside human labels.
- **L (phone)** The page is 860–927 px wide at 390 px.
- **X** Empty action-column header (axe).

### Operator console (index, tenant tabs, totals)

![Operator console](screenshots/12-operator-console-desktop.png)

| | |
|---|---|
| ![Entitlements](screenshots/13-operator-tenant-entitlements-desktop.png) | ![Login policy](screenshots/13b-operator-tenant-login-desktop.png) |
| ![Users tab](screenshots/13d-operator-tenant-users-desktop.png) | ![Spend](screenshots/13e-operator-tenant-spend-desktop.png) |

![Totals across tenants](screenshots/14-operator-aggregates-desktop.png)

- **L** Tenants are an inline list of links with "(slug) · status · admins: n". There is no table, and the tenant status (active/suspended) is plain grey text.
- **K** The new-tenant form has inputs with `border px-1` (about 20 px tall), different from every other form. Downloadable files are a long checkbox list where each label is a dot-separated sentence of title, publisher, licence and tags; a long title wraps across three lines with the checkbox centred against it.
- **T** "Notices" is an h2 at a different size from the card titles above it, and the notices are raw codes (`external_spend_50`).
- **C/X** The slug in the tenant title is slate-500 on the page background at 4.34:1 (axe: fails AA at 20 px normal weight).
- **K** Tabs are plain buttons with a 2 px underline on the active one, and the full-width rule below is black.
- **L** Entitlements use raw model and mode IDs as checkbox labels (`corpus_only`, `eu-fast`). The date input shows the US `mm/dd/yyyy` placeholder in an otherwise en-GB app.
- **L** Spend is a sentence ("External models: enabled · spent €312.50 of €500.00 (62%)") with no meter, and the thresholds are a bullet-less list. The usage table has no cell padding, so its headers collide ("Tokens inTokens outCost"), and numbers are not right-aligned.

### Content console (register, source, propose, takedowns, sites, site, tags)

![Register](screenshots/15-content-register-desktop.png)

| | |
|---|---|
| ![Source detail](screenshots/16-content-source-detail-desktop.png) | ![Site detail](screenshots/19b-content-site-detail-desktop.png) |
| ![Takedowns](screenshots/18-content-takedowns-desktop.png) | ![Propose](screenshots/17-content-propose-desktop.png) |
| ![Sites](screenshots/19-content-sites-desktop.png) | ![Tags](screenshots/20-content-tags-desktop.png) |

- **L** The console's nav is a row of underlined links beside the h1, followed by "Your roles: content_editor, content_reviewer" as raw IDs. It is a different nav pattern from the operator console's tabs.
- **K** Buttons here are outlined (`border` plus currentColor), while the operator console uses filled. "Withdraw site" is a pale-red outline that reads as disabled. Filter selects are about 20 px tall native selects.
- **C** Status is plain text ("failed", "ingesting", "withdrawn"), with only the takedown in red, and "possible replacement" is an amber pill. On the takedowns page an overdue timer is bold red, but the row is otherwise identical to one due in 5 days; the timer and status columns wrap.
- **A** In source detail, facts are stacked "Label: value" lines rather than a definition list. The "Review" card for an already-approved source shows only a rule and a takedown form. "Jobs" is an empty heading.
- **L** Site pages and register tables have no horizontal scroll on phone (sites 627 px, register 542 px, takedowns 483 px).
- **M** The register shows "Loading…" below the filters. With no rows it says "No sources match." in grey (15b), with no hint whether a filter or an empty register is the cause.

### Access-denied states

| | |
|---|---|
| ![Tenant admins only](screenshots/11d-tenant-admin-not-admin-desktop.png) | ![Content roles only](screenshots/15c-content-roles-only-desktop.png) |

- **M** "Tenant admins only.", "Operators only." and "Content roles only." are 14 px sentences at the top-left with no heading, no explanation and no way back.

## Full scenario list

| Scenario | What it shows |
|---|---|
| 01-signin-token | Phase 0 token sign-in |
| 02 / 02b / 02c / 02d | Email sign-in; SSO refused (`?sign_in=failed`); link sent; SSO choice |
| 03-finish-sign-in | Landing page of an emailed link |
| 04-app-loading | Before `/auth/mode` answers |
| 05 / 05b / 05c | Consent: first time; notice changed; notice failed to load |
| 06 / 06b / 06c / 06d / 06e | Conversations: populated; with admin and operator links; empty; loading; error |
| 07 / 07b / 07c / 07d / 07e / 07f / 07g / 07h | Start panel: single workspace and model; choices; external model chosen; model without reasoning; loading; error; no workspace; start refused |
| 08 / 08b / 08c / 08d / 08e / 08f | Chat: searching; streamed answer; citation open; retrieval error; spend-cap fallback notice; no-history tenant |
| 09 / 09b / 09c / 09d | Long answer with 14 citations (panel open, closed); abstained, unsupported, partial, truncated, failover; not found |
| 10 / 10b / 10c / 10d | Workspace files: populated with long titles; empty; loading; error |
| 11 / 11b / 11c / 11d | Tenant admin; version history open; remove confirmation; not an admin |
| 12 / 12b | Operator console; not an operator |
| 13 / 13b / 13c / 13d / 13e | Operator tenant tabs: entitlements, login, workspaces, users, spend |
| 14 | Totals across tenants |
| 15 / 15b / 15c | Content register; empty; no content role |
| 16 / 17 / 18 / 19 / 19b / 20 | Source detail; propose; takedowns; sites; site detail; tags |

## Top ten issues across the app, by visual impact

1. **Near-black `currentColor` borders on every card, table and input** (Tailwind v4 default). It makes the whole app look like a wireframe and hides the focus ring. Fix with a border token, and the app changes character at once.
2. **No app shell.** No persistent header, navigation, tenant or workspace context, or consistent sign-out; every page starts with "← Conversations".
3. **Horizontal overflow on phones**: 12 states are 416–927 px wide at 390 px. Missing `w-full` on page containers, and tables without scroll or stacked layouts.
4. **Phone citation panel opens below the composer**, out of view in any thread longer than a screen; on desktop the panel grows the page instead of scrolling in place. Citations are the product's core promise.
5. **Answer and notice Markdown loses its structure**: headings render as body text and bullets vanish. This affects answers and the consent notice.
6. **No type scale or defined font**: section titles, labels and table headers look identical, and the OS decides the typeface.
7. **Five button styles and three input sizes**, with underlined links used as actions, emoji feedback buttons, borderless selects and low-contrast disabled buttons.
8. **Unpadded, unaligned tables** (files, users, register, spend): wrapping dates, stacked row actions, and raw status codes instead of badges.
9. **Colour without a system**: amber means six different things, red means error, delete and "unsupported", there is no accent colour, and links and buttons look alike.
10. **Bare loading, empty, error and access-denied states**: one-line text at top-left with no heading, landmark, retry or next step. Related: weak focus visibility, and the consent notice has no tab stop of its own (Safari users cannot scroll it from the keyboard).
