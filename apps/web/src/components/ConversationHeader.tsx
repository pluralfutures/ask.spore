import type { ConversationDetail } from "../api/types";
import { formatDate } from "../lib/format";

// The conversation's fixed settings (P1a-12): workspace label, model name and a reasoning
// badge. Read-only: workspace, model and reasoning cannot change inside a conversation.
export function ConversationHeader({ conversation }: { conversation: ConversationDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-ui text-fg-secondary">
      <span data-testid="workspace-label" className="rounded-control bg-neutral-muted px-2">
        {conversation.workspace_name}
      </span>
      <span data-testid="model-name">{conversation.model_display_name}</span>
      {conversation.reasoning ? (
        <span
          data-testid="reasoning-badge"
          className="rounded-control bg-info-subtle px-2 text-meta font-emphasis text-info"
        >
          Reasoning on
        </span>
      ) : null}
      {conversation.mode === "general_knowledge" ? (
        <span className="rounded-control bg-warning-muted px-2 text-meta font-emphasis text-warning">
          General knowledge
        </span>
      ) : null}
      <span className="text-fg-muted">Expires {formatDate(conversation.expires_at)}</span>
    </div>
  );
}
