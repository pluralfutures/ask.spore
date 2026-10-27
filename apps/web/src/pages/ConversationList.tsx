import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ConversationLinks } from "../components/Conversations";
import { ButtonLink } from "../ui/Button";
import { Input } from "../ui/Input";
import { LINK } from "../ui/link";
import { PageHeader } from "../ui/PageHeader";

// HP-02: the full list's own route; the chat and start pages' back links lead here.
export const CONVERSATIONS_PATH = "/conversations";

// The conversation list (UX-13: the same rows as the chat's rail) and the workspaces'
// files. The home page (HP-04) shows the latest three and links here.
export function ConversationList() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  // P2B-03: the query lives in this component only. It is filtered in the browser over the
  // list already loaded: nothing is sent, and it is in no URL or storage.
  const [search, setSearch] = useState("");

  return (
    <div className="mx-auto w-full flex max-w-3xl flex-col gap-6 p-4 md:px-8 md:py-6">
      <PageHeader
        title="Conversations"
        // UX-10: Administration and the operator console (P1c-08) are in the top bar.
        actions={
          <ButtonLink to="/new" variant="primary" icon={Plus}>
            New conversation
          </ButtonLink>
        }
      />
      {conversations.data?.length ? (
        <div role="search" className="relative">
          <Search
            size={16}
            strokeWidth={1.5}
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-muted"
          />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search conversations by title"
            placeholder="Search by title"
            autoComplete="off"
            className="w-full pl-9"
          />
        </div>
      ) : null}
      <ConversationLinks variant="page" filter={search} onClearFilter={() => setSearch("")} />
      {workspaces.data?.length ? (
        <section className="text-ui">
          <h2 className="mb-1 font-strong">Files behind each workspace</h2>
          <ul className="flex flex-wrap gap-3">
            {workspaces.data.map((w) => (
              <li key={w.id}>
                <Link to={`/w/${w.id}/files`} className={LINK}>
                  {w.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
