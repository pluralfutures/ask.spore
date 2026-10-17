import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { loadCredentials, setUnauthorizedHandler, type Credentials } from "./api/client";
import { AiNotice } from "./components/AiNotice";
import { SignIn } from "./components/SignIn";
import { Chat } from "./pages/Chat";
import { ConversationList } from "./pages/ConversationList";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export function App() {
  const [credentials, setCredentials] = useState<Credentials | null>(loadCredentials);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      setCredentials(null);
    });
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-slate-100 text-slate-900">
      <AiNotice />
      {credentials ? (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<ConversationList />} />
              <Route path="/c/:id" element={<Chat />} />
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      ) : (
        <SignIn onSignedIn={setCredentials} />
      )}
    </div>
  );
}
