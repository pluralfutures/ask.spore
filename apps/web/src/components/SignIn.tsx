import { useState, type FormEvent } from "react";

import { saveCredentials, type Credentials } from "../api/client";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Field } from "../ui/Field";
import { AuthCard } from "./AuthCard";

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
    <AuthCard step="Sign in">
      <form onSubmit={submit} className="flex flex-col gap-4">
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
        <Button variant="primary" size="lg" type="submit">
          Sign in
        </Button>
      </form>
    </AuthCard>
  );
}
