// HP-03: whether the home page's welcome card was hidden (owner decision, Oct 26, 2026:
// remembered in the browser). One fixed key holding "1": no user ID or email, and never
// sent to the server. Storage can be missing or throw (private windows, blocked site
// data); then the card shows and Hide lasts for the page view only.

export const WELCOME_KEY = "sporebot.welcome-hidden";

type Store = Pick<Storage, "getItem" | "setItem">;

function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function welcomeHidden(store: Store | null = browserStore()): boolean {
  try {
    return store?.getItem(WELCOME_KEY) === "1";
  } catch {
    return false;
  }
}

export function rememberWelcomeHidden(store: Store | null = browserStore()): void {
  try {
    store?.setItem(WELCOME_KEY, "1");
  } catch {
    // Not remembered; the card is hidden for this page view only.
  }
}
