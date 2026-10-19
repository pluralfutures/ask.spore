import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import {
  authMode,
  currentUser,
  loadCredentials,
  setUnauthorizedHandler,
  signOut,
  type Credentials,
} from "./api/client";
import type { AuthMode } from "./api/types";
import { AiNotice } from "./components/AiNotice";
import { EmailSignIn } from "./components/EmailSignIn";
import { SignIn } from "./components/SignIn";
import { Chat } from "./pages/Chat";
import { ConversationList } from "./pages/ConversationList";
import { FinishSignIn } from "./pages/FinishSignIn";
import { NewConversation } from "./pages/NewConversation";
import { OperatorConsole } from "./pages/OperatorConsole";
import { TenantAdmin } from "./pages/TenantAdmin";
import { WorkspaceFiles } from "./pages/WorkspaceFiles";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

// The emailed link's landing page (P1a-02); the token is in the fragment.
export const FINISH_PATH = "/auth/finish";

function currentPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname;
}

function Signed({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ConversationList />} />
          <Route path="/new" element={<NewConversation />} />
          <Route path="/c/:id" element={<Chat />} />
          <Route path="/w/:id/files" element={<WorkspaceFiles />} />
          <Route path="/admin" element={<TenantAdmin />} />
          <Route path="/operator" element={<OperatorConsole />} />
        </Routes>
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
  const path = currentPath();

  useEffect(() => {
    if (mode === null) void authMode().then(setMode);
  }, [mode]);

  useEffect(() => {
    if (mode === "oidc" && path !== FINISH_PATH) {
      void currentUser().then((me) => setSignedIn(me !== null));
    }
  }, [mode, path]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      setCredentials(null);
      setSignedIn(false);
    });
  }, []);

  let body: React.ReactNode;
  if (path === FINISH_PATH) {
    body = <FinishSignIn onSignedIn={() => window.location.assign("/")} />;
  } else if (mode === null || (mode === "oidc" && signedIn === null)) {
    body = <p className="mx-auto mt-16 text-sm">Loading…</p>;
  } else if (mode === "oidc") {
    body = signedIn ? (
      <Signed>
        <button
          type="button"
          onClick={() => void signOut().then(() => setSignedIn(false))}
          className="mx-auto mb-4 text-sm underline"
        >
          Sign out
        </button>
      </Signed>
    ) : (
      <EmailSignIn />
    );
  } else {
    body = credentials ? <Signed>{null}</Signed> : <SignIn onSignedIn={setCredentials} />;
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-100 text-slate-900">
      <AiNotice />
      {body}
    </div>
  );
}
