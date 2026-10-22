import { useState, type FormEvent } from "react";

import { ApiError, discoverMethods, requestSignInLink, startSso } from "../api/client";
import type { DiscoverOut } from "../api/types";
import { ssoButtonLabel } from "../lib/sso";
import { failureText } from "./emailSignInText";

type Step = { kind: "email" } | { kind: "choose"; found: DiscoverOut } | { kind: "sent" };

// Sign-in (P1a-02, P1b-06, P1b-07). The page asks for an email address; its domain
// decides the methods (tenant discovery). An unknown domain gets the same answer as any
// domain without SSO, and the link answer is the same for every address. SSO sends the
// browser to the organisation's IdP, which sends it back to the API; a refused SSO
// sign-in comes back here as ?sign_in=failed, with no reason given.
export function EmailSignIn({ ssoFailed = false }: { ssoFailed?: boolean }) {
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<Step>({ kind: "email" });
  const [failed, setFailed] = useState(false);
  const [limited, setLimited] = useState(false);

  // P1b-08: too many sign-in requests from this network get 429.
  function fail(error: unknown) {
    setLimited(error instanceof ApiError && error.status === 429);
    setFailed(true);
  }

  async function sendLink() {
    setFailed(false);
    try {
      await requestSignInLink(email.trim());
      setStep({ kind: "sent" });
    } catch (error) {
      fail(error);
    }
  }

  async function goToSso() {
    setFailed(false);
    try {
      const url = await startSso(email.trim());
      if (url === null) setFailed(true);
      else window.location.assign(url);
    } catch (error) {
      fail(error);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailed(false);
    let found: DiscoverOut;
    try {
      found = await discoverMethods(email.trim());
    } catch (error) {
      fail(error);
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
        <button
          type="button"
          onClick={() => void goToSso()}
          className="rounded bg-slate-900 px-3 py-1.5 text-white"
        >
          {ssoButtonLabel(step.found.sso_kind)}
        </button>
        {step.found.methods.includes("sign_in_link") && (
          <button type="button" onClick={() => void sendLink()} className="text-sm underline">
            Email me a sign-in link instead
          </button>
        )}
        {failed && <p className="text-sm text-red-700">{failureText(limited)}</p>}
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
      {ssoFailed && !failed && (
        <p className="text-sm text-red-700">
          Single sign-on did not complete. Start again, or ask your administrator whether your
          account can use ask.spore.
        </p>
      )}
      {failed && <p className="text-sm text-red-700">{failureText(limited)}</p>}
    </form>
  );
}
