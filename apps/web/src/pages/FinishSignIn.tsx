import { useState } from "react";

import { completeSignIn } from "../api/client";
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

type State = "ready" | "working" | "failed" | "no_binding";

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

  async function finish() {
    if (token === null || state === "working") return;
    setState("working");
    const result = await completeSignIn(token);
    if (result === "ok") onSignedIn();
    else setState(result);
  }

  return (
    <main className="mx-auto mt-16 flex max-w-sm flex-col gap-3 px-4">
      <h1 className="text-xl font-semibold">ask.spore</h1>
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
