import type { InputHTMLAttributes, ReactNode } from "react";

import { CHECK, CHECK_LABEL, cx } from "./controlClass";

// UX-07: a checkbox or radio inside its label, so the text is the accessible name and the
// whole line can be clicked. Use Switch for a single on/off setting.

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "children"> & {
  children: ReactNode;
};

export function Checkbox({ children, className, ...rest }: Props) {
  return (
    <label className={cx(CHECK_LABEL, className)}>
      <input type="checkbox" className={CHECK} {...rest} />
      <span>{children}</span>
    </label>
  );
}

export function Radio({ children, className, ...rest }: Props) {
  return (
    <label className={cx(CHECK_LABEL, className)}>
      <input type="radio" className={CHECK} {...rest} />
      <span>{children}</span>
    </label>
  );
}
