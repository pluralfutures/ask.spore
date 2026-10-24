import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, MessageSquare, Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { formatDate } from "../lib/format";
import { Button, ButtonLink } from "../ui/Button";
import { LINK } from "../ui/link";
import { Notice } from "../ui/Notice";
import { EmptyState, Skeleton } from "../ui/States";
import { PageHeader } from "../ui/PageHeader";
import { useState } from "react";
import { ConfirmDialog } from "../ui/Dialog";

export function ConversationList() {
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const [deleting, setDeleting] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

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
      {conversations.isPending ? <Skeleton /> : null}
      {conversations.isError ? <Notice tone="danger">Could not load conversations.</Notice> : null}
      {conversations.data?.length === 0 ? (
        <EmptyState title="No conversations yet." icon={MessageSquare} />
      ) : null}
      {conversations.data?.length ? (
        <ul className="divide-y rounded-card border bg-surface">
          {conversations.data?.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-4 p-3">
              <Link to={`/c/${c.id}`} className="min-w-0 flex-1">
                <p className="truncate font-emphasis">{c.title ?? "Untitled conversation"}</p>
                <p className="flex items-center gap-1 text-ui text-fg-muted">
                  <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
                  Expires {formatDate(c.expires_at)}
                </p>
              </Link>
              <Button variant="ghost-danger" size="sm" onClick={() => setDeleting(c.id)}>
                Delete
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {/* UX-09: the confirmation is a dialog with the words of the former browser prompt. */}
      <ConfirmDialog
        open={deleting !== null}
        title="Delete this conversation permanently?"
        confirmLabel="Delete"
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
          setDeleting(null);
        }}
      />
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
