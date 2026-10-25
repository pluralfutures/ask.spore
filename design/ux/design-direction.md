# Design direction: "Quiet research desk"

Draft, Oct 23, 2026. A proposal for review, not yet a decision. Look and feel only: no branding, no new copy, no change to behaviour, flow or what any compliance element says. It goes with [audit.md](audit.md) and [../specs/ux-refresh-spec.md](../specs/ux-refresh-spec.md).

## Who it is for, and what that implies

- **Business development at a global agrifood company.** They use it between meetings, often on a laptop and sometimes on a phone. They want a fast answer they can quote, with the source in plain sight. Implication: the answer and its provenance dominate, settings stay out of the way, and the phone layout is a first-class layout, not an afterthought.
- **Policy analysts at international organisations.** They read long answers closely, check every citation and may paste passages into briefing notes. Implication: a comfortable reading measure and line height, real heading structure in answers, citations that stay beside the text while scrolling, good contrast, and full keyboard and screen-reader support. Many work under public-sector accessibility rules (EN 301 549 / WCAG 2.1 AA as a floor).
- **Tenant admins, operators and content staff.** They use dense tables and forms a few times a week. Implication: a compact density, consistent tables, status badges instead of raw codes, and the same controls as the chat app.

In the spirit of Linear and Stripe's dashboard: restrained neutrals, one accent, hairline borders, almost no shadows, typography and spacing doing the work. No gradients, illustrations or decorative colour.

## Typeface: Lato, self-hosted

- **Lato** (SIL Open Font License 1.1) for all UI and reading text. Weights **400, 700**, plus **400 italic** for emphasis in answers. Lato has no 500 or 600 weight in the common distributions; the scale below uses 400 and 700 only, and uses size and colour, not weight, for the finer steps.
- **Self-hosted, never fetched from Google.** The production CSP (`infra/caddy/Caddyfile`) is `font-src 'self'`, so a Google-hosted font would be blocked anyway. Vendor `woff2` files under `apps/web/src/assets/fonts/` (or install `@fontsource/lato`, which ships the same files into the bundle) with the OFL text alongside, and declare `@font-face` with `font-display: swap`.
- **Coverage.** The Google Fonts build of Lato (the one `@fontsource/lato` packages) covers Latin and Latin Extended, which is enough for English, French, Spanish and Portuguese source titles. Lato 2.0 (latofonts.com) adds Greek and Cyrillic; take it if the corpus will hold titles in those scripts. Either way the fallback stack keeps unsupported glyphs legible: `"Lato", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif`.
- **Numbers.** Tables and spend figures use `font-variant-numeric: tabular-nums` where the font supports it, and are right-aligned.
- **Brand word.** The "Mycelium" in the "Mycelium SporeBot" heading and top bar is **Poppins 700** (OFL, Latin subset, self-hosted under `apps/web/src/assets/fonts/poppins/`), the Mycelium Gastronomy logo typeface, used nowhere else (`font-brand` token).
- **Monospace** (IDs, slugs, config keys, certificate numbers): `ui-monospace, "SF Mono", Menlo, Consolas, monospace` at 13 px. No webfont.

## Type scale

Seven sizes. Line heights are on a 4 px grid. Names are the token names.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `text-display` | 28 / 36 | 700 | Sign-in and consent page titles only |
| `text-title` | 22 / 28 | 700 | Page title (one `h1` per page) |
| `text-heading` | 17 / 24 | 700 | Section and card titles (`h2`) |
| `text-subheading` | 15 / 22 | 700 | Sub-sections, answer `h2`/`h3`, citation titles |
| `text-body` | 14 / 20 | 400 | Default UI text, tables, forms |
| `text-reading` | 16 / 26 | 400 | Answer text and the consent notice (measure max 72ch) |
| `text-small` | 13 / 18 | 400 | Meta, help text, provenance, badges, table headers (700) |

Rules: table headers are `text-small` 700 in `--text-muted`, not uppercase. Labels are `text-body` 700. Help text is `text-small` in `--text-muted`. Never go below 13 px; the current 12 px citation markers and badges move to 13 px.

## Spacing scale

A 4 px base: `0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64`.

- Inside controls: 8 px vertical by 12 px horizontal (36 px tall), or 10 by 14 for large (44 px, every touch target on phone).
- Card and table cell padding: 16 px (12 px vertical in table rows). Card title to content: 12 px.
- Between fields in a form: 16 px. Between cards or sections: 24 px. Page header to content: 24 px. Page gutter: 32 px desktop, 16 px phone.
- Chat thread: 24 px between turns, 12 px between an answer and its notes.

## Colour

One neutral ramp, one accent, and status colours used **only** for status, never for decoration.

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--bg-canvas` | `#F6F7F9` | App background behind cards | |
| `--bg-surface` | `#FFFFFF` | Cards, tables, inputs, panels | |
| `--bg-subtle` | `#EEF0F3` | Hover rows, table header, selected nav, disabled controls | |
| `--border` | `#E2E5EA` | Hairlines between and around surfaces | decorative |
| `--border-strong` | `#C9CED6` | Dividers that must read, card hover | decorative |
| `--border-input` | `#868E9B` | Input, select, checkbox outlines | 3.3:1 on white (meets 1.4.11) |
| `--text` | `#171B22` | Primary text | 17.3:1 |
| `--text-secondary` | `#3B4250` | Secondary text, notes | 10.1:1 |
| `--text-muted` | `#5D6573` | Meta, help, table headers | 5.9:1 on white, 5.5:1 on canvas |
| `--text-placeholder` | `#6B7280` | Placeholders | 4.8:1 |
| `--accent` | `#2E5BBA` | Primary buttons, links, focus ring, selected state, citation markers | 6.3:1 (white on it 6.3:1) |
| `--accent-hover` | `#244A9A` | Hover and pressed | 8.3:1 |
| `--accent-subtle` | `#EDF2FC` | Selected citation, active nav item, info notices | accent-hover on it 7.4:1 |
| `--warning-text` / `--warning-bg` | `#7A4B00` / `#FDF5E3` | Things the user must weigh: external model, spend cap, partial or truncated answer | 6.8:1 |
| `--danger-text` / `--danger-bg` | `#A3271C` / `#FDF0EE` | Errors, destructive confirmation, unsupported answer | 6.6:1 |
| `--danger` | `#B42318` | Danger button fill | 6.6:1 with white |
| `--success-text` / `--success-bg` | `#17663F` / `#EBF6F0` | Saved, active, ingested | 6.3:1 |

Rules:

- **Accent is a slate blue**, chosen because it is neutral for both audiences, separate from every status colour, and not a brand colour. Swapping it later is one token.
- **Links are accent-coloured**, underlined on hover and always underlined inside running text (answers, notices), so they never rely on colour alone.
- **Amber means "weigh this"**, red means "failed or destructive", green means "done or healthy". The AI notice becomes neutral-informational (`--accent-subtle` with an info icon) because it is permanent, not a warning about this answer. Its text and position do not change.
- Status always pairs colour with a word (and an icon where space allows), never colour alone.

## Radius and shadow

- **Radius**: 6 px for controls (buttons, inputs, selects, chips), 8 px for cards, panels and tables, 10 px for dialogs and the phone bottom sheet. Badges 4 px. No fully rounded pills except the citation marker (it reads as a number token).
- **Shadow**: none on cards in the page flow; they are defined by `--border`. Only floating layers cast a shadow:
  - `--shadow-popover`: `0 1px 2px rgb(16 24 40 / 0.06), 0 4px 12px rgb(16 24 40 / 0.08)` for menus, select popovers and toasts.
  - `--shadow-overlay`: `0 8px 32px rgb(16 24 40 / 0.16)` for dialogs, the citation drawer on tablet and the phone bottom sheet.

## Focus and motion

- **Focus**: every interactive element shows `outline: 2px solid var(--accent); outline-offset: 2px` on `:focus-visible`. Inputs also switch their border to `--accent`. The ring never relies on the border colour, which was the problem before.
- **Motion**: 120 ms ease-out for hover and colour; 180 ms for the citation panel and bottom sheet. Everything respects `prefers-reduced-motion`.

## Layout

- **App shell** (all signed-in pages): the AI notice strip at the very top (unchanged text and place), then a 56 px top bar on `--bg-surface` with the product name, the tenant name, a primary nav (Conversations; Files; Administration, Operator and Content only for those roles) and a user menu holding sign-out. Below it, the page.
- **Chat layout** (desktop ≥1024 px): a 264 px left rail with "New conversation" and the conversation list (each with its expiry), the thread in the centre (max 760 px), and the citation panel as a 380 px right column that scrolls on its own and keeps the selected source in view. **Tablet** 768–1023 px: the rail collapses to a menu, and citations open in a right drawer. **Phone**: a single column; citations open in a bottom sheet over the thread (max 85% height, drag handle, close button), so tapping a marker always shows its source.
- **Admin and console pages**: a page header (title, one-line description, primary action on the right), then a tab bar or a left sub-nav for sections, then cards. Max content width 1120 px. Tables sit in a card with `overflow-x: auto`; on phone, tables with more than three columns switch to stacked rows (label/value pairs).
- **Fixed widths never set page width.** Every page container is `w-full max-w-… mx-auto` and every long string can wrap or truncate with a tooltip.

## Shared components

Each component is built once in `apps/web/src/ui/` and used everywhere. Behaviour stays where it is today; components carry look and accessibility only.

| Component | Variants and rules |
|---|---|
| **AppShell** | AI notice strip + top bar + optional left rail + main. Holds the skip link ("Skip to content") and the only `<main>`. |
| **PageHeader** | Breadcrumb (optional), `h1` title, description, actions slot, optional meta row of badges. |
| **Button** | `primary` (accent fill), `secondary` (surface, `--border-input` outline), `ghost` (text only, subtle hover), `danger` (red fill, only inside a confirmation). Sizes `sm` 32, `md` 36, `lg` 44. Optional leading icon. Loading state with spinner and kept width. Disabled: `--bg-subtle` fill and `--text-muted` text, never opacity. |
| **IconButton** | Square `sm`/`md`; requires `aria-label`; tooltip on hover. Replaces emoji feedback and close links. |
| **Field** | Label (700), control, help text, error text (`--danger-text`, with icon, linked via `aria-describedby`). |
| **Input / Textarea / Select** | 36 px tall, 6 px radius, `--border-input`, accent focus. Textarea auto-grows to a max. Select uses the native element styled, so keyboard and screen-reader behaviour is unchanged. |
| **Checkbox / Switch** | Checkbox for multi-select lists; Switch for a single on/off setting (reasoning, sign-in links, MFA). Both 20 px with a 44 px hit area on phone. |
| **Card** | Surface, 1 px `--border`, 8 px radius, 16–24 px padding, optional header (title, description, actions) and footer (save row). |
| **Table** | Header row on `--bg-subtle`, `text-small` 700 muted, 12/16 px cells, row hover, right-aligned numbers, one row-action menu ("⋯", an IconButton) instead of stacked links, visually-hidden header text for the action column. Wraps in an `overflow-x: auto` box; `stacked` mode on phone. |
| **Badge** | `neutral`, `accent`, `warning`, `danger`, `success`; 13 px text, 4 px radius, optional dot. Used for user status, source status, mode, reasoning, external, superseded, withdrawn. |
| **Notice** (inline alert) | `info`, `warning`, `danger`, `success`; icon, title (optional), body, optional action. Used for the spend-cap fallback, external-model note, no-history note, refusals and errors. |
| **EmptyState** | Icon, title, one sentence, optional primary action. |
| **Skeleton / Spinner** | Skeleton rows for lists and tables; inline spinner for buttons and "Searching your research package…". |
| **Tabs** | Underline tabs with accent indicator; `aria-current` kept; scroll horizontally on phone. |
| **Dialog** | Confirmations (delete conversation, remove user, withdraw site) replace `window.confirm` and in-row confirmations. Focus is trapped and returns to the trigger. |
| **Disclosure** | Version history, advanced settings; chevron icon, keyboard operable. |
| **CitationMarker** | 20 px tall rounded token, 13 px 700, accent-subtle fill, accent-hover text; 24×24 px minimum hit area; `aria-label="Citation n"`. |
| **SourceCard** | Marker, title (`text-subheading`), provenance line (publisher · date · page) in `text-small` muted that wraps by item, status badge (superseded/withdrawn) with its explanation, excerpt as a quote, "View at source" link. |
| **AnswerBlock** | Reading typography for Markdown (headings, lists, bold, links), answer-quality notices *inside* the block (partial, truncated, unsupported, failover), and a footer with Feedback. |
| **Feedback** | Two buttons with thumb up/down outline icons and their existing names ("Helpful", "Not helpful") as visible text on desktop, icon plus `aria-label` on phone; pressed state uses accent. |
| **RetentionIndicator** | Clock icon + today's text ("Expires 18 Nov 2026", or the no-history note) in the conversation header and list rows. Same words, now with an icon and a consistent place. |

Icons: one outline icon set at 16/20 px, 1.5 px stroke (for example Lucide, ISC, bundled, not fetched). Every icon-only control has an `aria-label`.

## What stays exactly as it is

The compliance elements listed in the spec's binding list keep their wording and their place in the flow: the consent gate, the AI transparency notice, citation provenance, the history and retention indicators, and feedback. The refresh restyles them; it does not move, shorten or hide them.
