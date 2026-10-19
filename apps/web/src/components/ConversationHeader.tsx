import type { ConversationDetail } from "../api/types";
import { formatDate } from "../lib/format";

// The conversation's fixed settings (P1a-12): workspace label, model name and a reasoning
// badge. Read-only: workspace, model and reasoning cannot change inside a conversation.
export function ConversationHeader({ conversation }: { conversation: ConversationDetail }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
      <span data-testid="workspace-label" className="rounded bg-slate-200 px-2">
        {conversation.workspace_name}
      </span>
      <span data-testid="model-name">{conversation.model_display_name}</span>
      {conversation.reasoning ? (
        <span
          data-testid="reasoning-badge"
          className="rounded bg-indigo-100 px-2 text-xs font-medium text-indigo-800"
        >
          Reasoning on
        </span>
      ) : null}
      {conversation.mode === "general_knowledge" ? (
        <span className="rounded bg-amber-100 px-2 text-xs font-medium text-amber-900">
          General knowledge
        </span>
      ) : null}
      <span className="text-slate-600">Expires {formatDate(conversation.expires_at)}</span>
    </div>
  );
}
