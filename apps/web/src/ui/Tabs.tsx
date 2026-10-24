import { Link } from "react-router-dom";

import { cx } from "./controlClass";

// UX-09: section tabs as links (each section has its own address), with an accent
// underline on the current one, aria-current="page", and sideways scrolling on a phone.
export interface Tab {
  label: string;
  to: string;
  current: boolean;
}

export function Tabs({ label, tabs }: { label: string; tabs: Tab[] }) {
  return (
    // w-0 min-w-full: the tab row never widens its container; it scrolls instead.
    <nav aria-label={label} className="w-0 min-w-full overflow-x-auto border-b">
      <ul className="flex min-w-max gap-1">
        {tabs.map((tab) => (
          <li key={tab.to}>
            <Link
              to={tab.to}
              aria-current={tab.current ? "page" : undefined}
              className={cx(
                "-mb-px inline-flex min-h-10 items-center border-b-2 px-3 text-ui max-sm:min-h-11",
                tab.current
                  ? "border-primary font-strong text-fg"
                  : "border-transparent text-fg-muted hover:border-line-input hover:text-fg",
              )}
            >
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
