# UX Refresh Build Spec

Oct 23, 2026 · Status: **approved by the owner on Oct 24, 2026 as its own phase** (decision 4 below), starting with Group A. **Group A (UX-01 to UX-03), UX-04 to UX-10 (Groups B and C), UX-11 to UX-16 were built on Oct 24, 2026.** All four open items were decided on Oct 24, 2026, so UX-14 and the screen items that show the new mockup labels are unblocked.

Sources: [../ux/audit.md](../ux/audit.md) (the visual audit, with screenshots) and [../ux/design-direction.md](../ux/design-direction.md) (the proposed look). Mockups of the chat view, start panel and tenant admin page, each beside its current screenshot, are on a design canvas: https://claude.ai/artifact/3spU4UTTXALVNbfdaFiRJE.

## Goal

Give the web app a restrained, professional look that suits business-development users at a global agrifood client and policy analysts at international organisations, and make it work at phone width, **without changing behaviour, copy or flow**, and without weakening any compliance element. The rebuild is split so that each item is a small, reviewable diff whose visual effect is shown by screenshot diffs, not by reading Tailwind classes.

Exit criteria (all must hold):

- The visual-regression suite (UX-01) covers every scenario in the audit at 1440 and 390 px, and its snapshots are the reviewed record of every visual change.
- No page is wider than the viewport at 390 px (UX-02 overflow check, zero exceptions).
- The axe baseline has no `serious` or `critical` violations, and none of any kind that the audit listed (UX-02).
- Every element of the binding compliance list below is present, with the same content and in the same place in the flow, checked by the contract tests of UX-03.
- `pnpm lint`, `pnpm typecheck`, `pnpm test` and the Playwright suites pass.

## Not in this refresh

Binding once approved. Record ideas in `backlog.md`.

- Copy changes, new features or new routes (except the development-only component gallery of UX-06). Where the direction or mockups show a new label (for example "Settings", "1 of 2"), it needs the owner's approval as copy before it is built; otherwise the existing wording is used.
- Branding: logo, brand colours, marketing pages. The accent is a neutral token that a later branding pass can swap.
- Dark mode, per-tenant theming, right-to-left layouts.
- Search or filters on the files page, conversation search, renaming conversations.
- Any change to the API, the prompt, what is logged, or what is sent to a model.

## Binding compliance UI

These elements implement controls from the compliance guide (AI Act Art. 50 transparency, GDPR Art. 5(1)(e) retention, the Oct 17–19, 2026 addenda on external models and fixed retention, and P1b-10 consent). The refresh may restyle them. It may not change their wording, remove them, hide them behind an interaction they do not have today, or move them to a different place in the flow. UX-03 adds a test for each line before any visual work starts.

1. **Consent gate** (`ConsentGate`, P1b-10).
   - It replaces every conversation, file and tenant admin page until the active notice is accepted. The operator and content consoles are internal staff pages and are not gated (P1b-10, `lib/consent.ts`). The gate offers no navigation to the gated pages; sign-out may be shown.
   - It shows the notice title, the "changed since you last accepted" sentence when it applies, the "In short" summary and the "Full notice" in full, the checkbox "I have read the notice ({version}) and accept it.", and the "Accept and continue" button, which stays disabled until the box is ticked. The load-error and save-error sentences stay.
   - The full notice must remain completely readable: if it scrolls, the scroll region is keyboard-focusable (an audit finding to fix, not a change of content). Markdown headings and lists in the notice must render as headings and lists.
2. **AI transparency notice and answer labels.**
   - "AI-generated, verify against cited sources." (`AiNotice`, `role="note"`) stays the **first element on every page**, signed in or not, above the top bar. It is not dismissible, collapsible or hidden at any width.
   - The answer labels keep their text and stay attached to the answer they qualify: "Unsupported answer: no citations to your sources", "Nothing relevant found", the "General knowledge" mode badge in the conversation header, the partial, truncated and failover notes, and "Searching your research package…".
   - The external-model disclosures keep their text and place: the model label suffix "(served outside the EU)", the start panel note "This model is served outside the EU.", the spend-cap fallback notice in the conversation header, and the failover note on an answer served outside the EU.
3. **Citation provenance.**
   - Every cited source shows its marker, title, publisher, publication date (or "undated") and page or slide when known.
   - It also shows the superseded or withdrawn status with its explanatory sentence, the excerpt or the "quoted passage was removed" note, and "View at source" when there is a canonical URL.
   - Activating a marker shows that source **in view** at every width (on phone, a bottom sheet over the thread; on desktop, the panel scrolls the selected source into view). Markers keep their accessible name "Citation n".
4. **History and retention indicators.**
   - "Expires {date}" stays on every conversation in the list and in the conversation header.
   - The no-history note (`NO_HISTORY_NOTE`) stays in the chat for tenants with retention 0.
   - The tenant admin retention section keeps its explanation, its summary line and its 30-day maximum.
   - No control, label or placeholder may suggest a retention longer than 30 days. Delete conversation stays available from the list (behind a confirmation, as today).
5. **Feedback.**
   - "Helpful" and "Not helpful" stay on every stored answer, including "Nothing relevant found" answers, with `aria-pressed` and the "Feedback not saved" failure text.
   - They stay absent from no-history turns, as today.

## Technology notes

The refresh stays inside the stack decision (React, TypeScript, Vite, Tailwind CSS v4, Playwright, vitest). Three small additions need a line in `design/Stack Decision.md` in the item that introduces them. The PR description must say why.

- **Lato, self-hosted** (UX-05): either `@fontsource/lato` (bundled by Vite into `/assets`) or vendored `woff2` files with the OFL licence text. Never a Google Fonts URL. The production CSP is `font-src 'self'` (`infra/caddy/Caddyfile`), which already allows this and blocks Google.
- **Icons** (UX-06): one bundled outline set, `lucide-react` 1.53.0 (ISC; Lucide icons are ISC, not MIT), tree-shaken, no runtime fetch.
- **axe-core** (UX-02): `@axe-core/playwright` as a dev dependency.

Answer and notice Markdown styling is our own CSS (a `.prose-answer` layer in `index.css`), not the Tailwind typography plugin, so the rules stay few and reviewable.

## Work items

Build in this order. Each item is one PR, small enough to review in one sitting, and references its ID in commits (`UX-07: …`). Every item after UX-04 that changes pixels updates the reviewed snapshots in the same PR, and the PR shows the before and after images of the affected scenarios.

### Group A — Baselines (no visual change)

**UX-01 Visual-regression suite.**
- Turn the audit's throwaway script into `apps/web/e2e/visual/`: the stateful `FakeApi` extended with the audit's stress fixtures (a long structured answer with 14 citations, long titles, publishers and emails, superseded and withdrawn citations, empty lists, loading and error responses), and the same scenario list.
- Use `toHaveScreenshot` at 1440×900 and 390×844, full page, animations off, after `document.fonts.ready`. Snapshots are committed and are generated on Linux Chromium. The suite has its own config (`pnpm test:visual`) and stays out of CI until UX-05: today the app renders in the machine's system font, so pixels differ between machines. With bundled Lato, UX-05 adds a CI job that runs the suite in the pinned Playwright image and regenerates the snapshots there.
- Synthetic data only (CLAUDE.md).
- Tests: the suite passes against today's app. A deliberately changed colour fails it.

**UX-02 Accessibility and layout baseline.**
- `@axe-core/playwright` runs on every scenario (WCAG 2.1 A/AA plus best practice). Today's violations are written to a reviewed allow-list (rule and target); any new violation fails.
- An overflow check asserts `document.documentElement.scrollWidth <= innerWidth` at 390 px. Today's 12 failing states go on its allow-list.
- A keyboard test tabs through sign-in, start, chat (including opening and closing a citation) and the consent gate, asserting the order and that focus is visible (a computed outline of at least 2 px).
- Later items shrink both allow-lists; nothing may add to them.

**UX-03 Compliance UI contract tests.**
- One Playwright test per line of the binding list above. Each asserts the exact text, its landmark or container, and its order relative to neighbours (for example, the AI notice is the first element in `body`, and each conversation row contains "Expires").
- Each test also covers the negative case: the gate blocks `/`, `/new`, `/admin`, `/c/:id` and the files page until accepted, and the consoles stay reachable.
- These tests are the guard for every later item and are never updated in the same PR as a visual change, unless the owner approves a wording change separately.

### Group B — Tokens and global styles

**UX-04 Theme tokens, no pixel change.**
- Define semantic tokens in `index.css` with Tailwind v4 `@theme` (colour, type, spacing, radius, shadow names from design-direction.md), with **values set to what the app renders today**, including the `currentColor` border and the inherited system font.
- Replace raw utility colours and sizes in components with the semantic names.
- The visual-regression diff must be zero. No component structure changes.

**UX-05 Apply the direction's values and Lato.**
- Change the token values to the proposed palette, type scale, radius and focus ring. Add self-hosted Lato (400, 700, 400 italic) with `font-display: swap`. Add explicit `--border` colours and a global `:focus-visible` ring.
- The code diff is one CSS file plus the font files; the pixel diff is app-wide and reviewed from snapshots.
- Tests: the axe allow-list loses its focus and contrast entries; a test asserts no request leaves the origin for fonts.

### Group C — Shared components

Each component lives in `apps/web/src/ui/`, is shown on a development-only gallery route (`/_ui`, compiled out of production builds by `import.meta.env.DEV`) that the visual suite captures, and replaces the hand-written equivalents across the app in the same PR. Behaviour is unchanged.

**UX-06 Button, IconButton, link styles and the icon set.**
- Variants and sizes as in design-direction.md; disabled is a colour state, not opacity.
- Underlined text links used as actions become ghost buttons, and the emoji feedback buttons become icon buttons with their existing names.
- Tests: every button has an accessible name; touch targets are at least 44 px at 390 px.

**UX-07 Form controls.**
- `Field`, `Input`, `Textarea`, `Select`, `Checkbox`, `Switch`, with one height, label, help and error pattern linked by `aria-describedby`.
- Replaces the three input paddings and the borderless selects.

**UX-08 Surfaces and feedback.**
- `Card`, `PageHeader`, `Badge` (with the status-to-badge mapping for users, sources, sites, takedowns and jobs, keeping the shown words), `Notice`, `EmptyState`, `Skeleton` and `Spinner`.
- Raw status codes shown to users keep their meaning but render through the mapping. Any change of the shown word is copy and needs approval.

**UX-09 Table, Tabs, Disclosure, Dialog.**
- The table gets a scroll container and a stacked mode under 640 px, a visually hidden action-column header and a row-action menu.
- `Dialog` replaces `window.confirm` and the in-row removal confirmation, with focus trap and return.
- Tests: Escape closes; focus returns to the trigger.

**UX-10 App shell.**
- The AI notice strip (unchanged), the top bar (product name, tenant name, role-dependent nav, user menu with sign-out), a skip link and exactly one `<main>`.
- Page containers become `w-full`, which removes the cause of most phone overflow.
- The OIDC sign-out button below the content moves into the user menu, with the same action.
- Tests: UX-03 still passes; the axe `region` and `landmark-one-main` entries leave the allow-list.

### Group D — Screens, one per item

Each screen item applies the components, the layout from design-direction.md and the mockup where one exists, and clears that screen's entries from the UX-02 allow-lists.

- **UX-11 Sign-in pages:** email, SSO choice, link sent, token sign-in, finish and second factor. They get a centred card, an `h1` and a `main`. Built Oct 24, 2026: one `AuthCard` (`components/AuthCard.tsx`) with "SporeBot" as the `h1` in `text-display`; the second-factor code field shows its existing name "Code" as a visible label; the link-sent state gets a mail icon. The two second-factor states joined the scenarios (03b, 03c). No wording changed.
- **UX-12 Consent gate:** structured Markdown, a keyboard-scrollable notice, and the accept row kept in view on phone. Binding list item 1 applies in full. Built Oct 24, 2026: the notice's `#` to `###` render as `h3` under "Full notice" (deeper levels keep theirs) and its lists get markers; the full notice has its own tab stop and scrolls in a box from 768 px; under 768 px the page scrolls and the checkbox and button stay in a sticky row at the bottom. The `scrollable-region-focusable` entries left the baseline. The load-error state still has no `h1` (its only text is the error sentence; a heading would be new copy), so `05c` stays in the baseline. No wording changed.
- **UX-13 Conversation list and rail:** the list becomes the chat's left rail on desktop and the home page on phone. Delete moves into a row menu with a dialog. The empty, loading and error states are added. Built Oct 24, 2026: one list (`components/Conversations.tsx`) as the home page and, from 1024 px, a 264 px rail (`nav` "Conversations", "New conversation", "Recent", the open conversation marked `aria-current`) on the start and chat pages; below 1024 px the existing "← Conversations" link leads to the list, so the tablet menu of the direction is not built (no new control without a need). Each row's menu holds "Delete"; deleting the open conversation goes home. The UX-03 delete and expiry tests now open the row menu first (same question, same rows).
- **UX-14 Start panel** (mockup 2): the question comes first and is labelled, then the settings card. The model is shown read-only when only one is enabled; today it is hidden. That visibility change was approved on Oct 24, 2026 (open item 3). The external-model note becomes a warning notice. Built Oct 24, 2026: the page's `h1` is "New conversation" (the panel's former legend, so no new copy) in every state, including loading, error and no workspace; the question has the visible label "Question" and comes first; the panel's legend is "Settings", with workspace and model side by side from 768 px and the locked-settings line with a lock icon; a single model reads "Model: {name}". The mockup's "Files in {workspace}" link under the workspace is not built (unapproved copy). The `page-has-heading-one` entries of 07 to 07h left the baseline.
- **UX-15 Chat thread and answer block** (mockup 1): reading typography for answers, answer-quality notes inside the answer block, feedback in the answer footer, a sticky composer, and the conversation header as badges plus the retention indicator. Built Oct 24, 2026: answers are an `article` at 16/26 (`text-reading`) with their headings (the model's `#` as `h2`) and list markers; the partial, truncated and failover notes sit inside the block under the text, the feedback in a footer below a rule; the question is a bubble at most 80% wide; the header has the title, workspace and model as badges, the reasoning and general-knowledge badges and the expiry, above a rule; the composer is sticky at the bottom. Thread width 760 px.
- **UX-16 Citation panel** (mockup 1): a self-scrolling column on desktop with the selected source scrolled into view; a drawer on tablet; a bottom sheet on phone. Markers are at least 24 px targets. Built Oct 24, 2026: one `CitationPanel`, a "Citations" landmark at every width: from 1024 px a 380 px sticky column whose list scrolls on its own and brings the selected source into view; from 768 px a fixed drawer on the right; on phone a bottom sheet (at most 85% high, drag handle) showing one source with "1 of 2", "Previous source" and "Next source". Escape closes it. Markers are 24 px; the marker buttons no longer remount when the panel opens, so focus stays on the one activated. The two UX-03 "in view" tests now pass and lost their `test.fail` marks. The desktop count beside "Sources" in the mockup is not built.
- **UX-17 Workspace files:** a table component with a stacked mode on phone; websites as a second table; an empty state.
- **UX-18 Tenant admin** (mockup 3): section sub-nav, a users table with badges and row menus, cards per section, monospace config values.
- **UX-19 Operator console index and totals:** tenants as a table with status badges; the downloadable-files table; notices as a table; totals with right-aligned numbers.
- **UX-20 Operator tenant page:** tab component, entitlements and login-policy forms on form components, users on the table, and spend with a meter and threshold rows.
- **UX-21 Content console: register and source detail.** One nav pattern (tabs, shared with the operator console), filter bar on form components, status badges, and source facts as a definition list.
- **UX-22 Content console: sites, site detail, takedowns, tags, propose.** Same treatment. Takedown urgency becomes a badge as well as the existing text.
- **UX-23 Access-denied, loading and error sweep:** "Tenant admins only.", "Operators only." and "Content roles only." become empty states with an `h1`, keeping their text. Every remaining bare "Loading…" becomes a skeleton.

### Group E — Close-out

**UX-24 Release check.**
- Run the full visual, axe, overflow and keyboard suites at both widths and confirm the allow-lists are empty, or that each remaining entry is accepted by the owner with a reason.
- Have someone outside the build do a manual pass with a screen reader (NVDA or VoiceOver) on sign-in, consent, start, chat with citations and tenant admin, and record it in a findings note.
- Update `design/ux/audit.md` with after-screenshots.

## Open items for the owner

All four items were decided on Oct 24, 2026.

1. ~~Approve or adjust the direction: the slate-blue accent, Lato, and the left-rail chat layout.~~ Approved Oct 24, 2026 (the owner's "Proceed" in reply to this question), and built in UX-05. The AI notice keeps its amber treatment until UX-10 moves it into the app shell as the neutral info strip, since restyling it changes a component.
2. ~~Copy shown in the mockups that is not in the app today: the "Settings" legend, "Question" as a visible label, "Recent" in the rail, "1 of 2" with previous and next in the phone source sheet, and the section sub-nav.~~ All approved by the owner on Oct 24, 2026; the screen items use this wording.
3. ~~UX-14: show the model read-only when a tenant has a single enabled model (today it is hidden).~~ Approved by the owner on Oct 24, 2026; UX-14 shows it.
4. ~~Which phase the refresh belongs to.~~ Decided Oct 24, 2026: the refresh is its own phase and starts now, with Group A.
