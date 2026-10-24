import type { ConversationDetail } from "../api/types";
import { formatDate } from "../lib/format";
import { Clock } from "lucide-react";
import { Badge } from "../ui/Badge";

// The conversation's fixed settings (P1a-12): workspace label, model name and a reasoning
// badge (UX-15: all badges), then the retention indicator. Read-only: workspace, model and reasoning cannot change inside a conversation.
export function ConversationHeader({ conversation }: { conversation: ConversationDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-meta text-fg-secondary">
      <Badge
        data-testid="workspace-label"
        title={conversation.workspace_name}
        className="block max-w-full truncate"
      >
        {conversation.workspace_name}
      </Badge>
      <Badge
        data-testid="model-name"
        title={conversation.model_display_name}
        className="block max-w-full truncate"
      >
        {conversation.model_display_name}
      </Badge>
      {conversation.reasoning ? (
        <Badge tone="accent" data-testid="reasoning-badge">
          Reasoning on
        </Badge>
      ) : null}
      {conversation.mode === "general_knowledge" ? (
        <Badge tone="warning">General knowledge</Badge>
      ) : null}
      <span className="ml-1 inline-flex items-center gap-1 text-meta text-fg-muted">
        <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
        Expires {formatDate(conversation.expires_at)}
      </span>
    </div>
  );
}
