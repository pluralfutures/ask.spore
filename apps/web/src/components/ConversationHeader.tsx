import type { ConversationDetail } from "../api/types";
import { formatDate } from "../lib/format";
import { Clock } from "lucide-react";
import { Badge } from "../ui/Badge";

// The conversation's fixed settings (P1a-12): workspace label, model name and a reasoning
// badge (UX-15: all badges), then the retention indicator. Read-only: workspace, model and reasoning cannot change inside a conversation.
// UX-24: a list, so a screen reader reads each item on its own rather than one run of words.
export function ConversationHeader({ conversation }: { conversation: ConversationDetail }) {
  return (
    <ul role="list" className="flex flex-wrap items-center gap-2 text-meta text-fg-secondary">
      <li className="min-w-0 max-w-full">
        <Badge
          data-testid="workspace-label"
          title={conversation.workspace_name}
          className="block max-w-full truncate"
        >
          {conversation.workspace_name}
        </Badge>
      </li>
      <li className="min-w-0 max-w-full">
        <Badge
          data-testid="model-name"
          title={conversation.model_display_name}
          className="block max-w-full truncate"
        >
          {conversation.model_display_name}
        </Badge>
      </li>
      {conversation.reasoning ? (
        <li>
          <Badge tone="accent" data-testid="reasoning-badge">
            Reasoning on
          </Badge>
        </li>
      ) : null}
      {conversation.mode === "general_knowledge" ? (
        <li>
          <Badge tone="warning">General knowledge</Badge>
        </li>
      ) : null}
      <li className="ml-1 inline-flex items-center gap-1 text-meta text-fg-muted">
        <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
        Expires {formatDate(conversation.expires_at)}
      </li>
    </ul>
  );
}
