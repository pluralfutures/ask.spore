import { useState, type FormEvent } from "react";

import { saveCredentials, type Credentials } from "../api/client";

// PHASE 0 ONLY: shared token + seeded email (P0-06). Replaced by Authentik in Phase 1.
export function SignIn({ onSignedIn }: { onSignedIn: (credentials: Credentials) => void }) {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const credentials = { token: token.trim(), email: email.trim() };
    saveCredentials(credentials);
    onSignedIn(credentials);
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
      <label className="flex flex-col gap-1 text-sm">
        Access token
        <input
          type="password"
          required
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="rounded border px-2 py-1"
        />
      </label>
      <button type="submit" className="rounded bg-slate-900 px-3 py-1.5 text-white">
        Sign in
      </button>
    </form>
  );
}
