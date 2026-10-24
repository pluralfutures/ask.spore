import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";

// UX-06: a square button with only an icon. The label is required: it is the accessible
// name and the hover tooltip.

export type IconButtonVariant = "ghost" | "secondary";

const BASE =
  "inline-flex shrink-0 items-center justify-center rounded-control border text-fg-secondary " +
  "not-disabled:hover:text-fg disabled:cursor-not-allowed disabled:text-fg-muted max-sm:size-11";

const SIZE = { sm: "size-8", md: "size-9" } as const;

const VARIANT: Record<IconButtonVariant, string> = {
  ghost: "border-transparent not-disabled:hover:bg-neutral-muted",
  secondary:
    "border-line-input bg-surface not-disabled:hover:bg-surface-subtle disabled:border-line disabled:bg-neutral-muted",
};

export interface IconButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "children" | "aria-label" | "title"
> {
  label: string;
  icon: LucideIcon;
  variant?: IconButtonVariant;
  size?: keyof typeof SIZE;
}

export function IconButton({
  label,
  icon: Icon,
  variant = "ghost",
  size = "md",
  className = "",
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={[BASE, SIZE[size], VARIANT[variant], className].filter(Boolean).join(" ")}
      {...rest}
    >
      <Icon size={size === "sm" ? 16 : 20} strokeWidth={1.5} aria-hidden="true" />
    </button>
  );
}
