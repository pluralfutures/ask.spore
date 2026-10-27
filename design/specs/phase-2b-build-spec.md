# Phase 2B Build Spec — Draft

Oct 27, 2026 · Status: **Draft, collecting items. Not approved; nothing here is built.** The owner
selects the phase's scope, goal and exit criteria before any item starts · Starts after the
Phase 2A release

Source decisions: the owner's request of Oct 27, 2026 to schedule the `remark-gfm` option of
the backlog's UX-12 item (`backlog.md`, "Unscheduled (UX-12 build, Oct 24, 2026)").

## Goal

To be set by the owner when the scope is selected. Items collected so far are listed below.

## Not in this phase

Binding once the spec is approved. Record ideas in `backlog.md`.

- To be completed with the owner's scope selection.

## Work items

Every change keeps the CLAUDE.md rules and adds a test. Item IDs go in commit messages.

### Group A — Answer and notice rendering

**P2B-01 Markdown tables and other GFM in answers and the consent notice.** Models answer
with GitHub-flavoured Markdown tables (seen with Qwen, Oct 27, 2026: a three-column table
shown as one paragraph of `|` text). `react-markdown` without `remark-gfm` treats a table as a
plain paragraph and joins its lines with spaces. The same defect affects the consent notice's
section 8 table (`config/consent/v1.md`, "What we hold").

- Add `remark-gfm` as a web dependency, exact version pinned in `apps/web/package.json`, and
  record it in `design/Stack Decision.md` (web app row) with its licence and why.
- Pass it as a `remarkPlugins` entry in both render sites:
  `apps/web/src/components/AnswerMarkdown.tsx` and `apps/web/src/components/ConsentGate.tsx`.
  Raw HTML stays off (react-markdown's default); the plugin adds no HTML pass-through.
- Table styling with the existing design tokens: header row in the emphasis weight, cell
  borders and padding, left-aligned text unless the column's alignment row says otherwise. A
  wide table scrolls sideways inside its own container (`overflow-x: auto`, with a focusable,
  labelled region for keyboard users) so the page never scrolls horizontally at phone width.
- Citation markers inside table cells keep working: `[n]` in a cell renders as the citation
  button and opens the panel (`linkMarkers` runs before parsing, so this should hold; the test
  proves it).
- The other GFM features the plugin turns on (strikethrough, task-list checkboxes,
  autolinked bare URLs, footnotes) render with plain styling. Task-list checkboxes are
  read-only. Autolinked URLs go through the existing `a` component, so they open in a new tab
  with `rel="noopener noreferrer"` like any other answer link.
- Tests: a unit test that a GFM table in an answer renders as a `<table>` with header cells
  and a working citation button in a cell; one that a table in the consent notice renders as a
  `<table>`; one that raw HTML in an answer is still shown as text. Accessibility: the axe
  baseline passes on a chat page with a table. Visual: regenerate the baselines that show a
  table (consent page) in the pinned Playwright image, and add one for an answer with a wide
  table at phone width.
- No change to prompts, `config/models.toml` or anything the model sees. On completion,
  strike the UX-12 table item in `backlog.md` and point it here.
