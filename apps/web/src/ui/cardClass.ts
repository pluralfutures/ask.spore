import { cx } from "./controlClass";

// UX-08: a surface in the page flow: 1 px border, 8 px radius, 16 px padding, no shadow.
// Use cardClass on a form that is itself the card; it sets no layout of its own.
export const CARD = "rounded-card border bg-surface p-4";

export function cardClass(className?: string): string {
  return cx(CARD, className);
}
