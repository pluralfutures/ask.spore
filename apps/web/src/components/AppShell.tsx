import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { api, contentApi } from "../api/client";
import { isTenantAdmin } from "../lib/admin";
import { cx } from "../ui/controlClass";
import { Menu } from "../ui/Menu";
import { mustAccept } from "../lib/consent";
import { AiNotice } from "./AiNotice";
import { AppFooter } from "./AppFooter";
import { ProductName } from "./ProductName";

// UX-10 (design/ux/design-direction.md, "App shell"): every page is a banner landmark
// holding the AI notice (its first element, unchanged), the skip link and, signed in, the
// top bar; then the page's one <main>, then the footer with the Legal link (P2A-L1).
// #root lays them out (index.css).

export const MAIN_ID = "main";
// UX-24: where a page has the conversation rail, "Skip to content" skips it too and lands
// on the page itself (WithRail marks it).
export const SKIP_TARGET = "data-skip-target";

// The first stop for the keyboard: jumps past the top bar to the page.
export function SkipLink() {
  return (
    <a
      href={`#${MAIN_ID}`}
      onClick={(event) => {
        event.preventDefault();
        const target =
          document.querySelector<HTMLElement>(`[${SKIP_TARGET}]`) ??
          document.getElementById(MAIN_ID);
        target?.focus();
      }}
      className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-4 focus:z-30 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:text-ui focus:shadow-popover"
    >
      Skip to content
    </a>
  );
}

export function Shell({ topBar, children }: { topBar?: ReactNode; children: ReactNode }) {
  return (
    <>
      <div role="banner">
        <AiNotice />
        {topBar ?? <SkipLink />}
      </div>
      <Main>{children}</Main>
      <AppFooter />
    </>
  );
}

function Main({ children }: { children: ReactNode }) {
  return (
    <main
      id={MAIN_ID}
      tabIndex={-1}
      className="flex w-full min-w-0 flex-1 flex-col focus:outline-none"
    >
      {children}
    </main>
  );
}

interface NavItem {
  label: string;
  to: string;
  current: (path: string) => boolean;
}

const CHAT_PATHS = /^\/($|conversations$|new$|c\/|w\/)/;

// The product name, the tenant, a nav that depends on the user's roles, and the user menu
// (sign-out in OIDC mode, the same action as the former button below the page). While the
// use notice waits for acceptance, nothing links to the pages it gates (P1b-10); the
// internal consoles are not gated and stay.
export function TopBar({ onSignOut }: { onSignOut?: () => void }) {
  const { pathname } = useLocation();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const content = useQuery({ queryKey: ["content", "me"], queryFn: contentApi.me });
  // The consent page shows no navigation (UX-03 contract), not even this nav; its only link
  // is the footer's Legal link (P2A-L1, owner decision Oct 26, 2026).
  const gated = me.data?.consent_required === true;
  const onGate = mustAccept(me.data, pathname);
  const items: NavItem[] = [];
  if (!gated) {
    // HP-04: "Home" (owner, Oct 26, 2026); "Conversations" names the full list's page.
    items.push({ label: "Home", to: "/", current: (p) => CHAT_PATHS.test(p) });
    if (isTenantAdmin(me.data)) {
      items.push({ label: "Administration", to: "/admin", current: (p) => p === "/admin" });
    }
  }
  if (onGate) items.length = 0;
  else if (me.data?.operator) {
    items.push({
      label: "Operator console",
      to: "/operator",
      current: (p) => p.startsWith("/operator"),
    });
  }
  if (!onGate && content.data?.roles.length) {
    items.push({
      label: "Content console",
      to: "/content",
      current: (p) => p.startsWith("/content"),
    });
  }
  const name = me.data?.display_name ?? me.data?.email;
  return (
    <>
      {onGate ? null : <SkipLink />}
      <div className="border-b bg-surface">
        <div className="mx-auto flex min-h-14 w-full max-w-[70rem] flex-wrap items-center gap-x-6 px-4 pt-2 md:px-8 md:pt-0">
          <div className="flex min-w-0 items-baseline gap-2">
            {gated ? (
              <span className="text-heading font-strong">
                <ProductName />
              </span>
            ) : (
              <Link to="/" className="text-heading font-strong">
                <ProductName />
              </Link>
            )}
            {me.data ? (
              <span data-testid="tenant-name" className="truncate text-ui text-fg-muted">
                {me.data.tenant_display_name}
              </span>
            ) : null}
          </div>
          {items.length ? (
            <nav
              aria-label="Main"
              className="order-last w-0 min-w-full overflow-x-auto md:order-none md:w-auto md:min-w-0 md:flex-1"
            >
              <ul className="flex min-w-max gap-1">
                {items.map((item) => {
                  const current = item.current(pathname);
                  return (
                    <li key={item.to}>
                      <Link
                        to={item.to}
                        aria-current={current ? "page" : undefined}
                        className={cx(
                          "inline-flex min-h-11 items-center border-b-2 px-2 text-ui md:min-h-14",
                          current
                            ? "border-primary font-strong text-fg"
                            : "border-transparent text-fg-muted hover:text-fg",
                        )}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
          ) : null}
          <div className="ml-auto flex items-center">
            {name && onSignOut ? (
              <Menu
                label={`Account: ${name}`}
                text={name}
                items={[{ label: "Sign out", onSelect: onSignOut }]}
              />
            ) : name ? (
              <span className="text-ui text-fg-secondary">{name}</span>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}
