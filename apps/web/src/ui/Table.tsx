import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cx } from "./controlClass";

// UX-09: one table style (index.css, .ui-table): a header row on the subtle background,
// 12/16 px cells, row hover, right-aligned tabular numbers. The table sits in a card that
// scrolls sideways when it is wider than the page; under 640 px a stacked table shows
// each row as label and value pairs instead (each Td's label).
export function Table({
  children,
  stacked = true,
  className,
}: {
  children: ReactNode;
  stacked?: boolean;
  className?: string;
}) {
  return (
    <div className={cx("overflow-x-auto rounded-card border bg-surface", className)}>
      <table className={cx("ui-table", stacked && "ui-table-stacked")}>{children}</table>
    </div>
  );
}

export function Th({
  numeric,
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return <th scope="col" data-numeric={numeric || undefined} className={className} {...rest} />;
}

// The action column's header: visually hidden, so the column still has a name.
export function ActionsTh() {
  return (
    <th scope="col">
      <span className="sr-only">Actions</span>
    </th>
  );
}

// In the stacked mode a labelled cell is a two-column grid (label, value), so its content
// is wrapped in one element: several nodes stay together in the value column.
export function Td({
  label,
  numeric,
  children,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { label?: string; numeric?: boolean }) {
  return (
    <td data-label={label} data-numeric={numeric || undefined} {...rest}>
      {label === undefined ? children : <div className="min-w-0">{children}</div>}
    </td>
  );
}
