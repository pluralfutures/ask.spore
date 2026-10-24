import { MailCheck } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, discoverMethods, requestSignInLink, startSso } from "../api/client";
import type { DiscoverOut } from "../api/types";
import { ssoButtonLabel } from "../lib/sso";
import { AuthCard } from "./AuthCard";
import { failureText, ssoRefusalText } from "./emailSignInText";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Field } from "../ui/Field";
import { Notice } from "../ui/Notice";

type Step = { kind: "email" } | { kind: "choose"; found: DiscoverOut } | { kind: "sent" };

// Sign-in (P1a-02, P1b-06, P1b-07). The page asks for an email address; its domain
// decides the methods (tenant discovery). An unknown domain gets the same answer as any
// domain without SSO, and the link answer is the same for every address. SSO sends the
// browser to the organisation's IdP, which sends it back to the API; a refused SSO
// sign-in comes back here as ?sign_in=failed with a coarse reason (P1c-02).
export function EmailSignIn({
  ssoFailed = false,
  ssoReason = null,
}: {
  ssoFailed?: boolean;
  ssoReason?: string | null;
}) {
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
      <AuthCard>
        <div className="flex items-start gap-3">
          <MailCheck aria-hidden size={24} strokeWidth={1.5} className="shrink-0 text-primary" />
          <p className="text-ui">
            If this address can sign in, a link is on its way. Open it in this browser within 15
            minutes.
          </p>
        </div>
      </AuthCard>
    );
  }
  if (step.kind === "choose") {
    return (
      <AuthCard>
        <Button variant="primary" size="lg" onClick={() => void goToSso()}>
          {ssoButtonLabel(step.found.sso_kind)}
        </Button>
        {step.found.methods.includes("sign_in_link") && (
          <Button variant="ghost" onClick={() => void sendLink()}>
            Email me a sign-in link instead
          </Button>
        )}
        {failed && <Notice tone="danger">{failureText(limited)}</Notice>}
      </AuthCard>
    );
  }
  return (
    <AuthCard>
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
        <Button variant="primary" size="lg" type="submit">
          Continue
        </Button>
        {ssoFailed && !failed && (
          <Notice tone="danger" role="alert">
            {ssoRefusalText(ssoReason)}
          </Notice>
        )}
        {failed && <Notice tone="danger">{failureText(limited)}</Notice>}
      </form>
    </AuthCard>
  );
}
