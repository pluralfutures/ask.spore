import { useEffect, useRef, type ReactNode } from "react";

import { cardClass } from "../ui/cardClass";

const PRODUCT = "SporeBot";

// The browser tab's title for a sign-in step (UX-24): the step first, so it is what a
// screen reader announces and what a tab strip shows.
function stepTitle(step: string): string {
  return `${step} – ${PRODUCT}`;
}

// The last step shown in this page load: a later, different step moves focus to its
// heading, since the step changes without a page load. The first step shown leaves focus
// where the browser puts it, so "Skip to content" stays the first stop.
let lastStep: string | null = null;

// UX-11: the sign-in pages (email, SSO choice, link sent, token sign-in, finish and second
// factor) share one centred card with the product name as the page's h1.
// UX-24 (owner approval, Oct 24, 2026): each step names itself in an h2 under it and in
// the tab title. `stepId` tells apart steps that share a heading ("Sign in").
export function AuthCard({
  step,
  stepId = step,
  children,
}: {
  step: string;
  stepId?: string;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = stepTitle(step);
    if (lastStep !== null && lastStep !== stepId) heading.current?.focus();
    lastStep = stepId;
  }, [step, stepId]);

  useEffect(
    () => () => {
      document.title = PRODUCT;
    },
    [],
  );

  return (
    <div className="flex flex-1 items-start justify-center px-4 py-8 md:items-center md:py-16">
      <div
        data-testid="auth-card"
        className={cardClass("flex w-full max-w-sm flex-col gap-4 md:p-6")}
      >
        <div className="flex flex-col gap-1">
          <h1 className="text-display font-strong">{PRODUCT}</h1>
          <h2 ref={heading} tabIndex={-1} className="text-heading font-strong focus:outline-none">
            {step}
          </h2>
        </div>
        {children}
      </div>
    </div>
  );
}
