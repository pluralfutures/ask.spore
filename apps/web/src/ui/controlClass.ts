// UX-07 (design/ux/design-direction.md, "Input / Textarea / Select"): one look for text
// controls: 36 px tall, the input line colour, an accent border on focus (the global
// focus ring stays), a danger border when invalid, and disabled as a colour state.

export const CONTROL =
  "min-h-9 rounded-control border border-line-input bg-surface px-3 py-1.5 text-ui text-fg " +
  "focus-visible:border-primary aria-invalid:border-danger " +
  "disabled:cursor-not-allowed disabled:border-line disabled:bg-neutral-muted disabled:text-fg-muted";

// A file input keeps the native control; only its button is styled like a secondary Button.
export const FILE_CONTROL =
  "text-ui text-fg-secondary file:mr-3 file:min-h-9 file:cursor-pointer file:rounded-control " +
  "file:border file:border-solid file:border-line-input file:bg-surface file:px-3.5 " +
  "file:text-ui file:font-strong file:text-fg hover:file:bg-surface-subtle";

// Checkbox and radio: 20 px, the accent when checked (accent-color in index.css).
export const CHECK = "size-5 shrink-0 disabled:cursor-not-allowed";

// The label around a checkbox, radio or switch: the whole line is the hit area, at least
// 44 px tall on phone (WCAG 2.5.5).
export const CHECK_LABEL =
  "inline-flex items-start gap-2 text-ui max-sm:min-h-11 max-sm:items-center";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
