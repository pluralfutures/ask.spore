import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ConversationLinks } from "../components/Conversations";
import { ButtonLink } from "../ui/Button";
import { LINK } from "../ui/link";
import { PageHeader } from "../ui/PageHeader";

// The home page: the conversation list (UX-13: the same rows as the chat's rail) and the
// workspaces' files.
export function ConversationList() {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });

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
      <ConversationLinks variant="page" />
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
