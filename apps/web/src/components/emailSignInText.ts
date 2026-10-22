export function failureText(limited: boolean): string {
  return limited
    ? "Too many sign-in attempts from this network. Wait a few minutes and try again."
    : "Something went wrong. Try again.";
}
