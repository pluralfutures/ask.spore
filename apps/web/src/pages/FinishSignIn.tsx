import { useState, type FormEvent } from "react";

import { answerMfa, completeSignIn, type SignInResult } from "../api/client";
import type { MfaRequiredOut } from "../api/types";
import { AuthCard } from "../components/AuthCard";
import { QrCode } from "../components/QrCode";
import { setupKey, validCode } from "../lib/mfa";
import { tokenFromFragment } from "../lib/fragment";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";
import { Field } from "../ui/Field";
import { Input } from "../ui/Input";
import { Notice } from "../ui/Notice";

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
    <AuthCard>
      {state === "no_binding" ? (
        <p className="text-ui">
          Open this link in the same browser window where you asked for it. A link works only there,
          once, for 15 minutes.{" "}
          <a href="/" className={LINK}>
            Ask for a new link
          </a>{" "}
          from the browser you want to use.
        </p>
      ) : token === null || state === "failed" ? (
        <p className="text-ui">
          This sign-in link cannot be used. Links work once, in the browser where you asked for
          them, for 15 minutes.{" "}
          <a href="/" className={LINK}>
            Ask for a new link
          </a>
          .
        </p>
      ) : (
        <Button variant="primary" size="lg" onClick={finish} disabled={state === "working"}>
          Click to finish logging in
        </Button>
      )}
    </AuthCard>
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
    <AuthCard>
      {key ? (
        <div className="flex flex-col gap-3 text-ui">
          <p>
            Administrators confirm each sign-in with an authenticator app. Scan this code with your
            app, or add the key below to it (time-based, 6 digits), then enter the code it shows.
          </p>
          {challenge.setup_uri && (
            <QrCode text={challenge.setup_uri} label="QR code for your authenticator app" />
          )}
          <code className="w-fit rounded-control border bg-surface-subtle px-2 py-1 font-mono">
            {key}
          </code>
          {challenge.setup_uri && (
            <a href={challenge.setup_uri} className={LINK}>
              Open in an authenticator app on this device
            </a>
          )}
        </div>
      ) : (
        <p className="text-ui">Enter the code from your authenticator app.</p>
      )}
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Code">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Field>
        <Button variant="primary" size="lg" type="submit" disabled={working || !validCode(code)}>
          Confirm
        </Button>
      </form>
      {challenge.failed && (
        <Notice tone="danger">That code was not accepted. Try the current one.</Notice>
      )}
    </AuthCard>
  );
}
