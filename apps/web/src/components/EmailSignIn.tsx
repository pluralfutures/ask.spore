import { useState, type FormEvent } from "react";

import { requestSignInLink } from "../api/client";

// Sign-in links (P1a-02). The answer is the same for every address.
export function EmailSignIn() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailed(false);
    try {
      await requestSignInLink(email.trim());
      setSent(true);
    } catch {
      setFailed(true);
    }
  }

  if (sent) {
    return (
      <main className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
        <h1 className="text-xl font-semibold">ask.spore</h1>
        <p className="text-sm">
          If this address can sign in, a link is on its way. Open it in this browser within 15
          minutes.
        </p>
      </main>
    );
  }
  return (
    <form onSubmit={submit} className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
      <h1 className="text-xl font-semibold">ask.spore</h1>
      <label className="flex flex-col gap-1 text-sm">
        Email
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded border px-2 py-1"
        />
      </label>
      <button type="submit" className="rounded bg-slate-900 px-3 py-1.5 text-white">
        Email me a sign-in link
      </button>
      {failed && <p className="text-sm text-red-700">Something went wrong. Try again.</p>}
    </form>
  );
}
