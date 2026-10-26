import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { buttonClass, type ButtonSize, type ButtonVariant } from "./buttonClass";

// UX-06: Button and ButtonLink share one class list (buttonClass.ts).

interface Common {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  children: ReactNode;
}

function Content({ icon: Icon, children }: Pick<Common, "icon" | "children">) {
  return (
    <>
      {Icon ? <Icon size={16} strokeWidth={1.5} aria-hidden="true" className="shrink-0" /> : null}
      {children}
    </>
  );
}

export type ButtonProps = Common & ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({
  variant,
  size,
  icon,
  className,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} {...rest}>
      <Content icon={icon}>{children}</Content>
    </button>
  );
}

export type ButtonLinkProps = Common & LinkProps;

// A navigation that looks like a button, such as "New conversation".
export function ButtonLink({ variant, size, icon, className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={buttonClass(variant, size, className)} {...rest}>
      <Content icon={icon}>{children}</Content>
    </Link>
  );
}
