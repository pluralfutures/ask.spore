import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ConversationLinks } from "../components/Conversations";
import { StartForm } from "../components/StartForm";
import { Welcome } from "../components/Welcome";
import { rememberWelcomeHidden, welcomeHidden } from "../lib/welcome";
import { LINK } from "../ui/link";
import { CONVERSATIONS_PATH } from "./ConversationList";

// HP-04 (design/specs/home-page-spec.md, mock-up D): the welcome card, the question box
// and the three most recent conversations. Once the welcome is hidden, the question's
// heading is the page's h1, and focus moves to it so it is not lost with the card.
export function Home() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  const [hidden, setHidden] = useState(welcomeHidden);
  const [justHidden, setJustHidden] = useState(false);
  const askHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (justHidden) askHeading.current?.focus();
  }, [justHidden]);

  function hide() {
    rememberWelcomeHidden();
    setHidden(true);
    setJustHidden(true);
  }

  const AskHeading = hidden ? "h1" : "h2";
  return (
    <div className="mx-auto flex w-full max-w-[50rem] flex-col gap-8 p-4 md:px-8 md:py-6">
      {/* Shown once the workspaces are known, so the steps do not change under the reader. */}
      {!hidden && !workspaces.isPending ? (
        <Welcome workspaceCount={workspaces.data?.length ?? 0} onHide={hide} />
      ) : null}
      <section aria-labelledby="ask-title" className="flex flex-col gap-4">
        <AskHeading
          id="ask-title"
          ref={askHeading}
          tabIndex={-1}
          className="text-title font-strong focus:outline-none"
        >
          What would you like to research?
        </AskHeading>
        <StartForm submitLabel="Ask" />
      </section>
      <section aria-labelledby="recent-title" className="flex flex-col gap-3">
        <h2 id="recent-title" className="text-heading font-strong">
          Recent conversations
        </h2>
        <ConversationLinks variant="page" limit={3} />
        {conversations.data?.length ? (
          <Link to={CONVERSATIONS_PATH} className={`w-fit text-ui ${LINK}`}>
            All conversations
          </Link>
        ) : null}
      </section>
    </div>
  );
}
