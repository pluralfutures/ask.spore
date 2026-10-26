// P2A-L1: the legal link at the bottom of every page, signed in or not, including the
// consent gate. "/legal" is a static page served by Caddy outside the app (P2A-L2): a plain
// link, no router, no request from this component, nothing in the URL that names a tenant
// or user. It opens in a new tab so a user keeps their place in the conversation.
export const LEGAL_PATH = "/legal";

export function AppFooter() {
  return (
    <footer className="border-t bg-surface">
      <nav
        aria-label="Legal"
        className="mx-auto flex min-h-10 w-full max-w-[70rem] items-center px-4 md:px-8"
      >
        <a
          href={LEGAL_PATH}
          target="_blank"
          rel="noopener"
          className="inline-flex min-h-6 items-center text-ui text-fg-muted underline underline-offset-2 hover:text-fg"
        >
          Legal<span className="sr-only"> (opens in a new tab)</span>
        </a>
      </nav>
    </footer>
  );
}
