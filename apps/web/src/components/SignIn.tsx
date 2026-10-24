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
      <h1 className="text-title font-strong">SporeBot</h1>
      <label className="flex flex-col gap-1 text-ui">
        Email
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-control border px-2 py-1"
        />
      </label>
      <label className="flex flex-col gap-1 text-ui">
        Access token
        <input
          type="password"
          required
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="rounded-control border px-2 py-1"
        />
      </label>
      <button type="submit" className="rounded-control bg-primary px-3 py-1.5 text-on-primary">
        Sign in
      </button>
    </form>
  );
}
