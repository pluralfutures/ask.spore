import { CircleAlert } from "lucide-react";
import { cloneElement, useId, type ReactElement, type ReactNode } from "react";

import { cx } from "./controlClass";

// UX-07: a label above its control, then optional help and error text. Help and error are
// linked to the control by aria-describedby, and an error sets aria-invalid, so screen
// readers read them with the field.

type ControlProps = { id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean };

export function Field({
  label,
  help,
  error,
  children,
  className,
}: {
  label: ReactNode;
  help?: ReactNode;
  error?: ReactNode;
  children: ReactElement<ControlProps>;
  className?: string;
}) {
  const generated = useId();
  const id = children.props.id ?? generated;
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy =
    [children.props["aria-describedby"], helpId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-ui font-strong">
        {label}
      </label>
      {cloneElement(children, {
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : children.props["aria-invalid"],
      })}
      {help ? (
        <p id={helpId} className="text-meta text-fg-muted">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="flex items-center gap-1 text-meta text-danger">
          <CircleAlert size={14} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
