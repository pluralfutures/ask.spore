import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { StartForm } from "../components/StartForm";
import { LINK } from "../ui/link";

// P1a-12: the start page. HP-01: the form is shared with the home page.
export function NewConversation() {
  return (
    <StartPage>
      <StartForm submitLabel="Start" />
    </StartPage>
  );
}

// Every state of the start page (loading, error, no workspace, the form) has the back link
// and the page's h1, the former legend of the panel.
function StartPage({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 md:px-8 md:py-6">
      <Link to="/" className={`w-fit text-ui ${LINK}`}>
        ← Conversations
      </Link>
      <h1 className="text-title font-strong">New conversation</h1>
      {children}
    </div>
  );
}
