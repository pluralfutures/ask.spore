// UX-06 (design/ux/design-direction.md, "Button"): the one button style of the app.
// Disabled is a colour state, never opacity, so the label stays readable. Hover styles
// use `not-disabled:` so they also apply to ButtonLink, which renders an <a>.

export type ButtonVariant =
  "primary" | "secondary" | "ghost" | "danger" | "secondary-danger" | "ghost-danger";

export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-control border text-ui font-strong " +
  "disabled:cursor-not-allowed max-sm:min-h-11 max-sm:min-w-11";

// At 390 px every size grows to the 44 px touch target (max-sm above).
const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-8 px-2.5",
  md: "min-h-9 px-3.5",
  lg: "min-h-11 px-4",
};

const DISABLED_FILLED = "disabled:border-line disabled:bg-neutral-muted disabled:text-fg-muted";

const VARIANT: Record<ButtonVariant, string> = {
  primary: `border-primary bg-primary text-on-primary not-disabled:hover:border-primary-hover not-disabled:hover:bg-primary-hover ${DISABLED_FILLED}`,
  secondary: `border-line-input bg-surface text-fg not-disabled:hover:bg-surface-subtle ${DISABLED_FILLED}`,
  ghost:
    "border-transparent text-fg-secondary not-disabled:hover:bg-neutral-muted not-disabled:hover:text-fg disabled:text-fg-muted",
  danger: `border-danger bg-danger text-on-danger not-disabled:hover:border-danger-strong not-disabled:hover:bg-danger-strong ${DISABLED_FILLED}`,
  "secondary-danger": `border-danger bg-surface text-danger not-disabled:hover:bg-danger-subtle ${DISABLED_FILLED}`,
  "ghost-danger":
    "border-transparent text-danger not-disabled:hover:bg-danger-subtle disabled:text-fg-muted",
};

// A toggle (aria-pressed) shows its pressed state in the accent.
const PRESSED = "aria-pressed:border-primary aria-pressed:bg-info-subtle aria-pressed:text-info";

export function buttonClass(
  variant: ButtonVariant = "secondary",
  size: ButtonSize = "md",
  className = "",
): string {
  return [BASE, SIZE[size], VARIANT[variant], PRESSED, className].filter(Boolean).join(" ");
}
