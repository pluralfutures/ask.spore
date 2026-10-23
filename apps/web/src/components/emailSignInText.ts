export function failureText(limited: boolean): string {
  return limited
    ? "Too many sign-in attempts from this network. Wait a few minutes and try again."
    : "Something went wrong. Try again.";
}

// P1c-02: a refused SSO sign-in comes back as ?sign_in=failed&reason=<reason>, one of the
// API's coarse reasons (app.auth.sso.REFUSAL_REASONS); the code itself never reaches the
// page, and an unknown reason reads as the generic one.
const SSO_REFUSALS: Record<string, string> = {
  domain:
    "Your organisation account is not at a domain this workspace accepts. Sign in with your work account, or ask your administrator.",
  unverified:
    "Your organisation has not verified this email address. Ask your administrator to verify it, then try again.",
  no_access: "This account does not have access to SporeBot. Ask your administrator to invite you.",
  start_again: "The sign-in expired or was opened in another browser. Start again in this browser.",
};

export function ssoRefusalText(reason: string | null): string {
  return (
    (reason && Object.hasOwn(SSO_REFUSALS, reason) ? SSO_REFUSALS[reason] : null) ??
    "Single sign-on did not complete. Start again, or ask your administrator whether your account can use SporeBot."
  );
}
