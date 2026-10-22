// Session renewal (P1b-08): the access token lives 8 hours; the app renews the session
// this long before it expires, from the HttpOnly refresh cookie it never sees.
export const RENEW_BEFORE_MS = 5 * 60 * 1000;
export const MIN_DELAY_MS = 30 * 1000;

// Milliseconds until the renewal, or null when the session has no known expiry.
export function renewalDelay(
  expiresAt: string | null | undefined,
  now = Date.now(),
): number | null {
  if (!expiresAt) return null;
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return null;
  return Math.max(at - now - RENEW_BEFORE_MS, MIN_DELAY_MS);
}
