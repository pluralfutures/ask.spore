import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, MessageSquare, Plus } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { SKIP_TARGET } from "./AppShell";
import { formatDate } from "../lib/format";
import { ButtonLink } from "../ui/Button";
import { cx } from "../ui/controlClass";
import { ConfirmDialog } from "../ui/Dialog";
import { Menu } from "../ui/Menu";
import { Notice } from "../ui/Notice";
import { EmptyState, Skeleton } from "../ui/States";

const UNTITLED = "Untitled conversation";

// UX-13: the conversation list, shown as the home page (and the only list on phone and
// tablet) and as the chat's left rail from 1024 px. Each row links to its conversation,
// shows its expiry (binding list item 4) and has a row menu whose "Delete" asks first.
export function ConversationLinks({
  variant,
  current = null,
}: {
  variant: "page" | "rail";
  current?: string | null;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });
  const [deleting, setDeleting] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: (_, id) => {
      if (id === current) navigate("/");
      return queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
  const rail = variant === "rail";

  let body: ReactNode;
  if (conversations.isPending) body = <Skeleton />;
  else if (conversations.isError)
    body = <Notice tone="danger">Could not load conversations.</Notice>;
  else if (conversations.data.length === 0)
    body = rail ? null : <EmptyState title="No conversations yet." icon={MessageSquare} />;
  else
    body = (
      <ul className={rail ? "flex flex-col gap-0.5" : "divide-y rounded-card border bg-surface"}>
        {conversations.data.map((c) => {
          const title = c.title ?? UNTITLED;
          const here = c.id === current;
          return (
            <li
              key={c.id}
              className={cx(
                "flex items-center gap-2",
                rail ? "rounded-control pr-1 hover:bg-surface-subtle" : "py-2 pr-2 pl-4",
                here && "bg-info-subtle hover:bg-info-subtle",
              )}
            >
              <Link
                to={`/c/${c.id}`}
                aria-current={here ? "page" : undefined}
                title={rail ? title : undefined}
                className={cx("flex min-w-0 flex-1 flex-col gap-0.5", rail ? "p-2" : "py-1")}
              >
                <span className={cx("truncate", here || !rail ? "font-strong" : null)}>
                  {title}
                </span>
                <span className="flex items-center gap-1 text-meta text-fg-muted">
                  <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
                  Expires {formatDate(c.expires_at)}
                </span>
              </Link>
              <Menu
                label={`Actions for ${title}`}
                items={[{ label: "Delete", danger: true, onSelect: () => setDeleting(c.id) }]}
              />
            </li>
          );
        })}
      </ul>
    );

  return (
    <>
      {body}
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
    </>
  );
}

// The chat's left rail (design direction, chat layout): from 1024 px only; below that the
// page's "← Conversations" link leads to the list.
export function ConversationRail({ current = null }: { current?: string | null }) {
  return (
    <nav
      aria-label="Conversations"
      className="hidden w-66 shrink-0 flex-col gap-4 border-r bg-surface px-3 py-4 lg:flex"
    >
      <ButtonLink to="/new" variant="primary" icon={Plus} className="w-full justify-center">
        New conversation
      </ButtonLink>
      <div className="flex flex-col gap-1.5">
        <p className="px-2 text-meta font-strong text-fg-muted">Recent</p>
        <ConversationLinks variant="rail" current={current} />
      </div>
    </nav>
  );
}

// The chat and start pages from 1024 px: the rail, then the page; the route's conversation
// is the current row.
export function WithRail({ children }: { children: ReactNode }) {
  const { id = null } = useParams();
  return (
    <div className="flex min-h-0 w-full flex-1">
      <ConversationRail current={id} />
      <div
        {...{ [SKIP_TARGET]: "" }}
        tabIndex={-1}
        className="flex min-w-0 flex-1 flex-col focus:outline-none"
      >
        {children}
      </div>
    </div>
  );
}
