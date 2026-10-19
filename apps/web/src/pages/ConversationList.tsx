import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { isTenantAdmin } from "../lib/admin";
import { formatDate } from "../lib/format";

export function ConversationList() {
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const remove = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  return (
    <main className="mx-auto max-w-3xl p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Conversations</h1>
        {isTenantAdmin(me.data) ? (
          <Link to="/admin" className="text-sm underline">
            Administration
          </Link>
        ) : null}
        <Link to="/new" className="rounded bg-slate-900 px-3 py-1.5 text-white">
          New conversation
        </Link>
      </div>
      {conversations.isPending ? <p>Loading…</p> : null}
      {conversations.isError ? <p className="text-red-700">Could not load conversations.</p> : null}
      {conversations.data?.length === 0 ? (
        <p className="text-slate-600">No conversations yet.</p>
      ) : null}
      <ul className="divide-y rounded border bg-white">
        {conversations.data?.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-4 p-3">
            <Link to={`/c/${c.id}`} className="min-w-0 flex-1">
              <p className="truncate font-medium">{c.title ?? "Untitled conversation"}</p>
              <p className="text-sm text-slate-600">Expires {formatDate(c.expires_at)}</p>
            </Link>
            <button
              type="button"
              onClick={() => {
                if (window.confirm("Delete this conversation permanently?")) remove.mutate(c.id);
              }}
              className="text-sm text-red-700 underline"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
