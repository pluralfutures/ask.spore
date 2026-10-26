import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

// UX-09: show and hide a section (version history, advanced settings). The native
// <details>, so it opens with Enter or Space and needs no script.
export function Disclosure({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-1 text-ui font-strong text-fg-secondary hover:text-fg max-sm:min-h-11 [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="transition-transform group-open:rotate-90 motion-reduce:transition-none"
        />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}
