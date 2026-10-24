import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

import type { Tone } from "../lib/status";
import { cx } from "./controlClass";

// UX-08: an inline alert: icon, optional title, the text, optional action. Used for the
// spend-cap fallback, the external-model note, the no-history note, refusals and errors.
// The text is passed in unchanged; the wrapper adds no words.
export type NoticeTone = Exclude<Tone, "neutral" | "accent"> | "info";

const STYLE: Record<NoticeTone, { box: string; icon: LucideIcon }> = {
  info: { box: "border-info-line bg-info-subtle text-fg", icon: Info },
  warning: { box: "border-warning-line bg-warning-subtle text-warning", icon: TriangleAlert },
  danger: { box: "border-danger-line bg-danger-subtle text-danger-strong", icon: CircleAlert },
  success: { box: "border-success-line bg-success-subtle text-success", icon: CircleCheck },
};

export function Notice({
  tone = "info",
  title,
  action,
  className,
  children,
  ...rest
}: Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  tone?: NoticeTone;
  title?: ReactNode;
  action?: ReactNode;
}) {
  const { box, icon: Icon } = STYLE[tone];
  return (
    <div
      className={cx(
        "flex items-start gap-2 rounded-control border px-3 py-2 text-ui",
        box,
        className,
      )}
      {...rest}
    >
      <Icon size={16} strokeWidth={1.5} aria-hidden="true" className="mt-0.5 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {title ? <p className="font-strong">{title}</p> : null}
        <div>{children}</div>
      </div>
      {action}
    </div>
  );
}
