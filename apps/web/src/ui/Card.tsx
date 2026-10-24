import type { HTMLAttributes, ReactNode } from "react";

import { cardClass } from "./cardClass";
import { cx } from "./controlClass";

// UX-08: a card with an optional header (title, description, actions).
export function Card({
  title,
  level = 2,
  description,
  actions,
  className,
  children,
  ...rest
}: Omit<HTMLAttributes<HTMLElement>, "title"> & {
  title?: ReactNode;
  level?: 2 | 3;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section className={cardClass(cx("flex flex-col gap-3", className))} {...rest}>
      {title || actions ? (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            {title ? <Heading className="text-heading font-strong">{title}</Heading> : null}
            {description ? <p className="text-ui text-fg-muted">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}
