import { useState, type FormEvent } from "react";

import { answerMfa, completeSignIn, type SignInResult } from "../api/client";
import type { MfaRequiredOut } from "../api/types";
import { setupKey, validCode } from "../lib/mfa";
import { tokenFromFragment } from "../lib/fragment";

// Landing page of the emailed sign-in link (P1a-02). Opening it submits nothing: only the
// button's POST sends the token, from this browser (the API checks it is the one that
// asked for the link). The token is read once per page load (StrictMode renders twice)
// and removed from the address bar.
let taken: string | null | undefined;

function takeToken(): string | null {
  if (typeof window === "undefined") return null;
  if (taken === undefined) {
    taken = tokenFromFragment(window.location.hash);
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }
  return taken;
}

type State = "ready" | "working" | "failed" | "no_binding" | MfaRequiredOut;

export function FinishSignIn({
  initialToken,
  onSignedIn,
}: {
  initialToken?: string | null;
  onSignedIn: () => void;
}) {
  const [token] = useState<string | null>(() =>
    initialToken === undefined ? takeToken() : initialToken,
  );
  const [state, setState] = useState<State>("ready");

  function settle(result: SignInResult) {
    if (result === "ok") onSignedIn();
    else setState(result);
  }

  async function finish() {
    if (token === null || state === "working") return;
    setState("working");
    settle(await completeSignIn(token));
  }

  if (typeof state === "object") {
    return <SecondFactor challenge={state} onResult={settle} />;
  }

  return (
    <main className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
      <h1 className="text-xl font-semibold">SporeBot</h1>
      {state === "no_binding" ? (
        <p className="text-sm">
          Open this link in the same browser window where you asked for it. A link works only there,
          once, for 15 minutes. <a href="/">Ask for a new link</a> from the browser you want to use.
        </p>
      ) : token === null || state === "failed" ? (
        <p className="text-sm">
          This sign-in link cannot be used. Links work once, in the browser where you asked for
          them, for 15 minutes. <a href="/">Ask for a new link</a>.
        </p>
      ) : (
        <button
          type="button"
          onClick={finish}
          disabled={state === "working"}
          className="rounded bg-slate-900 px-3 py-1.5 text-white"
        >
          Click to finish logging in
        </button>
      )}
    </main>
  );
}

// P1b-08: tenant admins confirm the sign-in with a code from their authenticator app; the
// first time, they add the key shown here to the app.
export function SecondFactor({
  challenge,
  onResult,
}: {
  challenge: MfaRequiredOut;
  onResult: (result: SignInResult) => void;
}) {
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const key = challenge.stage === "setup" ? setupKey(challenge.setup_uri) : null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validCode(code) || working) return;
    setWorking(true);
    const result = await answerMfa(code.trim());
    setWorking(false);
    setCode("");
    onResult(result);
  }

  return (
    <main className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
      <h1 className="text-xl font-semibold">SporeBot</h1>
      {key ? (
        <div className="flex flex-col gap-1 text-sm">
          <p>
            Administrators confirm each sign-in with an authenticator app. Add this key to your app
            (time-based, 6 digits), then enter the code it shows.
          </p>
          <code className="rounded bg-white px-2 py-1 font-mono">{key}</code>
          {challenge.setup_uri && (
            <a href={challenge.setup_uri} className="underline">
              Open in an authenticator app on this device
            </a>
          )}
        </div>
      ) : (
        <p className="text-sm">Enter the code from your authenticator app.</p>
      )}
      <form onSubmit={submit} className="flex flex-col gap-2">
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          aria-label="Code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="rounded border px-2 py-1"
        />
        <button
          type="submit"
          disabled={working || !validCode(code)}
          className="rounded bg-slate-900 px-3 py-1.5 text-white"
        >
          Confirm
        </button>
      </form>
      {challenge.failed && (
        <p className="text-sm text-red-700">That code was not accepted. Try the current one.</p>
      )}
    </main>
  );
}
