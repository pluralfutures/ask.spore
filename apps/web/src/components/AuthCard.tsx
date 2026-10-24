import type { ReactNode } from "react";

import { cardClass } from "../ui/cardClass";

// UX-11: the sign-in pages (email, SSO choice, link sent, token sign-in, finish and second
// factor) share one centred card with the product name as the page's h1.
export function AuthCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-start justify-center px-4 py-8 md:items-center md:py-16">
      <div
        data-testid="auth-card"
        className={cardClass("flex w-full max-w-sm flex-col gap-4 md:p-6")}
      >
        <h1 className="text-display font-strong">SporeBot</h1>
        {children}
      </div>
    </div>
  );
}
