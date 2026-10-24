import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import {
  authMode,
  currentUser,
  loadCredentials,
  refreshSession,
  setUnauthorizedHandler,
  signOut,
  type Credentials,
} from "./api/client";
import type { AuthMode } from "./api/types";
import { AiNotice } from "./components/AiNotice";
import { ConsentGate } from "./components/ConsentGate";
import { EmailSignIn } from "./components/EmailSignIn";
import { SignIn } from "./components/SignIn";
import { Chat } from "./pages/Chat";
import { ConversationList } from "./pages/ConversationList";
import { renewalDelay } from "./lib/session";
import { FinishSignIn } from "./pages/FinishSignIn";
import { NewConversation } from "./pages/NewConversation";
import { OperatorAggregates } from "./pages/OperatorAggregates";
import { OperatorConsole } from "./pages/OperatorConsole";
import { ContentConsole } from "./pages/content/ContentConsole";
import { OperatorTenant } from "./pages/OperatorTenant";
import { TenantAdmin } from "./pages/TenantAdmin";
import { WorkspaceFiles } from "./pages/WorkspaceFiles";
import { Button } from "./ui/Button";
import { Loading } from "./ui/States";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

// UX-06: the development-only component gallery. `import.meta.env.DEV` is false in a
// production build, so neither the route nor the gallery's code is included there.
const Gallery = import.meta.env.DEV ? lazy(() => import("./ui/Gallery")) : null;
export const GALLERY_PATH = "/_ui";

// The emailed link's landing page (P1a-02); the token is in the fragment.
export const FINISH_PATH = "/auth/finish";

function currentPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname;
}

// A refused SSO sign-in returns to the sign-in page with ?sign_in=failed (P1b-07) and,
// from P1c-02, &reason=<coarse reason>.
function ssoFailed(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("sign_in") === "failed";
}

function ssoReason(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("reason");
}

function Signed({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ConsentGate>
          <Routes>
            <Route path="/" element={<ConversationList />} />
            <Route path="/new" element={<NewConversation />} />
            <Route path="/c/:id" element={<Chat />} />
            <Route path="/w/:id/files" element={<WorkspaceFiles />} />
            <Route path="/admin" element={<TenantAdmin />} />
            <Route path="/operator" element={<OperatorConsole />} />
            <Route path="/content/*" element={<ContentConsole />} />
            <Route path="/operator/tenants/:tenantId" element={<OperatorTenant />} />
            <Route path="/operator/aggregates" element={<OperatorAggregates />} />
          </Routes>
        </ConsentGate>
      </BrowserRouter>
      {children}
    </QueryClientProvider>
  );
}

export function App({ initialMode = null }: { initialMode?: AuthMode | null } = {}) {
  const [mode, setMode] = useState<AuthMode | null>(initialMode);
  const [credentials, setCredentials] = useState<Credentials | null>(loadCredentials);
  // OIDC mode: null until GET /me answers.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const path = currentPath();

  useEffect(() => {
    if (mode === null) void authMode().then(setMode);
  }, [mode]);

  useEffect(() => {
    if (mode === "oidc" && path !== FINISH_PATH) {
      void currentUser().then((me) => {
        setSignedIn(me !== null);
        setExpiresAt(me?.session_expires_at ?? null);
      });
    }
  }, [mode, path]);

  // P1b-08: renew the session before it expires; if renewal is refused, the next request
  // gets 401 and the sign-in page shows.
  useEffect(() => {
    const delay = signedIn ? renewalDelay(expiresAt) : null;
    if (delay === null) return;
    const timer = window.setTimeout(() => {
      void refreshSession().then(async (renewed) => {
        if (!renewed) return;
        const me = await currentUser();
        setExpiresAt(me?.session_expires_at ?? null);
      });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [signedIn, expiresAt]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      setCredentials(null);
      setSignedIn(false);
    });
  }, []);

  let body: React.ReactNode;
  if (Gallery && path === GALLERY_PATH) {
    body = (
      <Suspense fallback={null}>
        <Gallery />
      </Suspense>
    );
  } else if (path === FINISH_PATH) {
    body = <FinishSignIn onSignedIn={() => window.location.assign("/")} />;
  } else if (mode === null || (mode === "oidc" && signedIn === null)) {
    body = <Loading className="mx-auto mt-16" />;
  } else if (mode === "oidc") {
    body = signedIn ? (
      <Signed>
        <Button
          variant="ghost"
          size="sm"
          className="mx-auto mb-4"
          onClick={() => void signOut().then(() => setSignedIn(false))}
        >
          Sign out
        </Button>
      </Signed>
    ) : (
      <EmailSignIn ssoFailed={ssoFailed()} ssoReason={ssoReason()} />
    );
  } else {
    body = credentials ? <Signed>{null}</Signed> : <SignIn onSignedIn={setCredentials} />;
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas text-fg">
      <AiNotice />
      {body}
    </div>
  );
}
