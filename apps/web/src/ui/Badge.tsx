import type { HTMLAttributes } from "react";

import { statusTone, type StatusKind, type Tone } from "../lib/status";
import { cx } from "./controlClass";

// UX-08: a short label in a tinted box, 13 px, 4 px radius. Colour carries the meaning
// as a second cue only: the word always says it.
const TONE: Record<Tone, string> = {
  neutral: "bg-neutral-muted text-fg-secondary",
  accent: "bg-info-subtle text-info",
  warning: "bg-warning-muted text-warning",
  danger: "bg-danger-subtle text-danger-strong",
  success: "bg-success-subtle text-success",
};

export function Badge({
  tone = "neutral",
  className,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cx(
        "inline-flex w-fit items-center rounded-badge px-1.5 text-meta font-emphasis whitespace-nowrap",
        TONE[tone],
        className,
      )}
      {...rest}
    />
  );
}

// A status word from the API, shown as it is, in its tone (lib/status.ts).
export function StatusBadge({
  kind,
  status,
  ...rest
}: Omit<HTMLAttributes<HTMLSpanElement>, "children"> & { kind: StatusKind; status: string }) {
  return (
    <Badge tone={statusTone(kind, status)} {...rest}>
      {status}
    </Badge>
  );
}
