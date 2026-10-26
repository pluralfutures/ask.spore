import type { InputHTMLAttributes, ReactNode } from "react";

import { CHECK_LABEL, cx } from "./controlClass";

// UX-07: a single on/off setting (reasoning, sign-in links, MFA). A native checkbox with
// role="switch", so it is announced as on or off and toggles with Space, drawn as a
// 36 by 20 px track with a sliding knob.
const TRACK =
  "relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-control bg-line-input " +
  "transition-colors checked:bg-primary disabled:cursor-not-allowed disabled:bg-line " +
  "before:absolute before:top-0.5 before:left-0.5 before:size-4 before:rounded-[0.25rem] " +
  "before:bg-surface before:transition-transform checked:before:translate-x-4 " +
  "motion-reduce:transition-none motion-reduce:before:transition-none";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "role" | "children"> & {
  children: ReactNode;
};

export function Switch({ children, className, ...rest }: Props) {
  return (
    <label className={cx(CHECK_LABEL, className)}>
      <input type="checkbox" role="switch" className={TRACK} {...rest} />
      <span>{children}</span>
    </label>
  );
}
