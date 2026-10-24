import { ExternalLink } from "lucide-react";
import type { AnchorHTMLAttributes } from "react";

import { cx } from "./controlClass";
import { LINK } from "./link";

// UX-24 (owner approval, Oct 24, 2026): a link that opens in a new tab says so. Sighted
// users see the external-link icon; screen readers hear "(opens in a new tab)" after the
// link text, which stays first so the visible label is still the start of the name.
export function NewTabLink({
  className,
  children,
  ...rest
}: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "target" | "rel">) {
  return (
    <a
      target="_blank"
      rel="noopener noreferrer"
      className={cx("inline-flex w-fit items-center gap-1", LINK, className)}
      {...rest}
    >
      {children}
      <ExternalLink size={14} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
