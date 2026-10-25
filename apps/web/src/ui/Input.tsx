import {
  forwardRef,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { CONTROL, FILE_CONTROL, cx } from "./controlClass";

// UX-07: the native elements, styled. Keyboard, autofill and screen-reader behaviour are
// the browser's own. Labels come from a wrapping <label> or from Field.

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, type, ...rest }, ref) {
    return (
      <input
        ref={ref}
        type={type}
        className={cx(type === "file" ? FILE_CONTROL : CONTROL, className)}
        {...rest}
      />
    );
  },
);

// Grows with its content (CSS field-sizing) from `rows` lines up to 16 rem; browsers
// without field-sizing keep the fixed `rows` height.
export function Textarea({
  className,
  rows = 3,
  style,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={rows}
      className={cx(CONTROL, "field-sizing-content max-h-64 py-2", className)}
      style={{ minHeight: `calc(${rows} * 1.25rem + 1.125rem)`, ...style }}
      {...rest}
    />
  );
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(CONTROL, "pr-2", className)} {...rest} />;
}
