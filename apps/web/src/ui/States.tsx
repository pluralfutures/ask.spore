import { Inbox, LoaderCircle, Lock, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "./controlClass";

// UX-08: loading and empty states.

// A spinning ring for "working" states; hidden from assistive technology, so the text
// beside it is what is announced. Still when the user prefers reduced motion.
export function Spinner({ className }: { className?: string }) {
  return (
    <LoaderCircle
      size={16}
      strokeWidth={2}
      aria-hidden="true"
      className={cx("shrink-0 animate-spin text-primary motion-reduce:animate-none", className)}
    />
  );
}

// "Loading…" with a spinner, announced politely.
export function Loading({
  children = "Loading…",
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <p role="status" className={cx("flex items-center gap-2 text-ui text-fg-muted", className)}>
      <Spinner />
      {children}
    </p>
  );
}

// Grey placeholder rows in the shape of a list that is still loading.
export function Skeleton({ rows = 3, label = "Loading…" }: { rows?: number; label?: string }) {
  return (
    <div role="status" className="flex flex-col gap-2">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="flex flex-col gap-1.5 rounded-card border bg-surface p-4"
        >
          <span className="h-3.5 w-2/3 rounded-badge bg-neutral-muted motion-safe:animate-pulse" />
          <span className="h-3 w-1/4 rounded-badge bg-neutral-muted motion-safe:animate-pulse" />
        </div>
      ))}
    </div>
  );
}

// Nothing to show yet: an icon, the sentence the page already uses, and an optional
// action.
export function EmptyState({
  title,
  children,
  action,
  icon: Icon = Inbox,
  className,
  ...rest
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  icon?: LucideIcon;
  className?: string;
  "data-testid"?: string;
}) {
  return (
    <div
      className={cx(
        "flex flex-col items-center gap-2 rounded-card border border-dashed bg-surface px-4 py-8 text-center text-ui",
        className,
      )}
      {...rest}
    >
      <Icon size={20} strokeWidth={1.5} aria-hidden="true" className="text-fg-subtle" />
      <p className="text-fg-secondary">{title}</p>
      {children ? <p className="text-fg-muted">{children}</p> : null}
      {action}
    </div>
  );
}

// UX-23: a page the user's role does not open: the page's h1 is the sentence the page
// already uses ("Tenant admins only."), in an empty state with a lock.
export function AccessDenied({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-3xl p-4 md:px-8 md:py-6">
      <div className="flex flex-col items-center gap-2 rounded-card border border-dashed bg-surface px-4 py-10 text-center">
        <Lock size={24} strokeWidth={1.5} aria-hidden="true" className="text-fg-subtle" />
        <h1 className="text-heading font-strong">{children}</h1>
      </div>
    </div>
  );
}

// A whole page that is still loading: the page's container around a skeleton.
export function PageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-3xl p-4 md:px-8 md:py-6">
      <Skeleton />
    </div>
  );
}
