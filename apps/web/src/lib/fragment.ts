// The emailed sign-in link carries its token in the URL fragment (P1a-02): a fragment is
// never sent to a server, so a mail scanner that fetches the link spends nothing.
export function tokenFromFragment(hash: string): string | null {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const token = params.get("token");
  return token && token.length <= 512 ? token : null;
}
