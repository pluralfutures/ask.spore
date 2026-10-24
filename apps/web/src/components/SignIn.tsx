import { useState, type FormEvent } from "react";

import { saveCredentials, type Credentials } from "../api/client";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Field } from "../ui/Field";

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
      <Field label="Email">
        <Input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>
      <Field label="Access token">
        <Input
          type="password"
          required
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </Field>
      <Button variant="primary" type="submit">
        Sign in
      </Button>
    </form>
  );
}
