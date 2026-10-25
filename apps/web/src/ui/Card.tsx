import { useId, type HTMLAttributes, type ReactNode } from "react";

import { cardClass } from "./cardClass";
import { cx } from "./controlClass";

// UX-08: a card with an optional header (title, description, actions). With `group`, the
// card is a group named by its title (UX-24), so a screen reader says which card a control
// belongs to when several cards repeat the same fields.
export function Card({
  title,
  level = 2,
  group = false,
  description,
  actions,
  className,
  children,
  ...rest
}: Omit<HTMLAttributes<HTMLElement>, "title"> & {
  title?: ReactNode;
  level?: 2 | 3;
  group?: boolean;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  const headingId = useId();
  const named = group && title ? { role: "group", "aria-labelledby": headingId } : {};
  return (
    <section className={cardClass(cx("flex flex-col gap-3", className))} {...named} {...rest}>
      {title || actions ? (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            {title ? (
              <Heading id={headingId} className="text-heading font-strong">
                {title}
              </Heading>
            ) : null}
            {description ? <p className="text-ui text-fg-muted">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}
