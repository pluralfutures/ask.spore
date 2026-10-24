import type { ConversationDetail } from "../api/types";
import { formatDate } from "../lib/format";
import { Clock } from "lucide-react";
import { Badge } from "../ui/Badge";

// The conversation's fixed settings (P1a-12): workspace label, model name and a reasoning
// badge. Read-only: workspace, model and reasoning cannot change inside a conversation.
export function ConversationHeader({ conversation }: { conversation: ConversationDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-ui text-fg-secondary">
      <Badge data-testid="workspace-label">{conversation.workspace_name}</Badge>
      <span data-testid="model-name">{conversation.model_display_name}</span>
      {conversation.reasoning ? (
        <Badge tone="accent" data-testid="reasoning-badge">
          Reasoning on
        </Badge>
      ) : null}
      {conversation.mode === "general_knowledge" ? (
        <Badge tone="warning">General knowledge</Badge>
      ) : null}
      <span className="inline-flex items-center gap-1 text-fg-muted">
        <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
        Expires {formatDate(conversation.expires_at)}
      </span>
    </div>
  );
}
