// Second factor for tenant admins (P1b-08). Enrolment shows the key from Authentik's
// otpauth:// URI, grouped for typing into an authenticator app; nothing is stored.
export function setupKey(uri: string | null | undefined): string | null {
  if (!uri?.startsWith("otpauth://")) return null;
  let secret: string | null;
  try {
    secret = new URL(uri).searchParams.get("secret");
  } catch {
    return null;
  }
  if (!secret || !/^[A-Z2-7]+=*$/i.test(secret)) return null;
  return (secret.toUpperCase().match(/.{1,4}/g) ?? []).join(" ");
}

export function validCode(code: string): boolean {
  return /^[0-9]{6,8}$/.test(code.trim());
}
