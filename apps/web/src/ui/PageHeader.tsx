import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { LINK } from "./link";

// UX-08: the top of a page: an optional back link, the one h1, a one-line description,
// actions on the right, and an optional row of badges.
export function PageHeader({
  title,
  description,
  actions,
  back,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
  meta?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-1">
      {back ? (
        <Link to={back.to} className={`w-fit text-ui ${LINK}`}>
          {back.label}
        </Link>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-title font-strong">{title}</h1>
        {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      </div>
      {description ? <p className="text-ui text-fg-muted">{description}</p> : null}
      {meta ? <div className="flex flex-wrap items-center gap-2 text-ui">{meta}</div> : null}
    </header>
  );
}
