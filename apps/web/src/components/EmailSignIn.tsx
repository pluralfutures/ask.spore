import { useState, type FormEvent } from "react";

import { discoverMethods, requestSignInLink } from "../api/client";
import type { DiscoverOut } from "../api/types";

type Step = { kind: "email" } | { kind: "choose"; found: DiscoverOut } | { kind: "sent" };

// Sign-in (P1a-02, P1b-06). The page asks for an email address; its domain decides the
// methods (tenant discovery). An unknown domain gets the same answer as any domain
// without SSO, and the link answer is the same for every address.
export function EmailSignIn() {
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<Step>({ kind: "email" });
  const [failed, setFailed] = useState(false);

  async function sendLink() {
    setFailed(false);
    try {
      await requestSignInLink(email.trim());
      setStep({ kind: "sent" });
    } catch {
      setFailed(true);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailed(false);
    let found: DiscoverOut;
    try {
      found = await discoverMethods(email.trim());
    } catch {
      setFailed(true);
      return;
    }
    if (found.methods.includes("sso")) {
      setStep({ kind: "choose", found });
    } else {
      await sendLink();
    }
  }

  if (step.kind === "sent") {
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
  if (step.kind === "choose") {
    return (
      <main className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
        <h1 className="text-xl font-semibold">ask.spore</h1>
        <p className="text-sm">Your organisation signs in with single sign-on.</p>
        {step.found.methods.includes("sign_in_link") && (
          <button type="button" onClick={() => void sendLink()} className="text-sm underline">
            Email me a sign-in link instead
          </button>
        )}
        {failed && <p className="text-sm text-red-700">Something went wrong. Try again.</p>}
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
        Continue
      </button>
      {failed && <p className="text-sm text-red-700">Something went wrong. Try again.</p>}
    </form>
  );
}
