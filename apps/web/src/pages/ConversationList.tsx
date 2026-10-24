import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { isTenantAdmin } from "../lib/admin";
import { formatDate } from "../lib/format";
import { Button, ButtonLink } from "../ui/Button";
import { LINK } from "../ui/link";

export function ConversationList() {
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const remove = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  return (
    <main className="mx-auto max-w-3xl p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-title font-strong">Conversations</h1>
        {isTenantAdmin(me.data) ? (
          <Link to="/admin" className={`text-ui ${LINK}`}>
            Administration
          </Link>
        ) : null}
        {/* P1c-08: operators reach their console from the chat app. */}
        {me.data?.operator ? (
          <Link to="/operator" className={`text-ui ${LINK}`}>
            Operator console
          </Link>
        ) : null}
        <ButtonLink to="/new" variant="primary" icon={Plus}>
          New conversation
        </ButtonLink>
      </div>
      {conversations.isPending ? <p>Loading…</p> : null}
      {conversations.isError ? <p className="text-danger">Could not load conversations.</p> : null}
      {conversations.data?.length === 0 ? (
        <p className="text-fg-muted">No conversations yet.</p>
      ) : null}
      <ul className="divide-y rounded-control border bg-surface">
        {conversations.data?.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-4 p-3">
            <Link to={`/c/${c.id}`} className="min-w-0 flex-1">
              <p className="truncate font-emphasis">{c.title ?? "Untitled conversation"}</p>
              <p className="text-ui text-fg-muted">Expires {formatDate(c.expires_at)}</p>
            </Link>
            <Button
              variant="ghost-danger"
              size="sm"
              onClick={() => {
                if (window.confirm("Delete this conversation permanently?")) remove.mutate(c.id);
              }}
            >
              Delete
            </Button>
          </li>
        ))}
      </ul>
      {workspaces.data?.length ? (
        <section className="mt-6 text-ui">
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
    </main>
  );
}
