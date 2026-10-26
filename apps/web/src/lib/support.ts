// Time-boxed support access (P2A-08): a tenant admin lets the operators read the
// settings or one of the admin's own conversations for 15 minutes to 4 hours.
import type { OperatorSupportGrant, SupportGrant } from "../api/types";

export const SUPPORT_DURATIONS = [15, 30, 60, 120, 240] as const;
export const DEFAULT_SUPPORT_MINUTES = 60;
export const MAX_SUPPORT_NOTE = 500;

export function durationLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`;
  const hours = minutes / 60;
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

export const SUPPORT_STATE_LABELS: Record<SupportGrant["state"], string> = {
  open: "Open",
  used: "Open, viewed",
  expired: "Expired",
  revoked: "Revoked",
};

export function grantScope(grant: Pick<SupportGrant, "scope" | "conversation_title">): string {
  if (grant.scope === "settings") return "Settings";
  return grant.conversation_title ? `Conversation: ${grant.conversation_title}` : "Conversation";
}

export function canRevoke(grant: SupportGrant): boolean {
  return grant.state === "open" || grant.state === "used";
}

export function viewsLabel(grant: SupportGrant): string {
  if (grant.views === 0) return "Not viewed";
  return grant.views === 1 ? "Viewed once" : `Viewed ${grant.views} times`;
}

export function grantRefusal(code: string | null): string {
  switch (code) {
    case "conversation_required":
      return "Choose the conversation to share.";
    case "conversation_not_found":
      return "That conversation is not one of yours, or it has expired.";
    case "note_required":
      return "Say what the operator should look at.";
    case "not_open":
      return "This access has already ended.";
    default:
      return "The access could not be granted.";
  }
}

// The operator's route to what a grant covers.
export function grantTarget(grant: OperatorSupportGrant): string {
  return grant.scope === "settings" ? "settings" : `conversation ${grant.conversation_id ?? ""}`;
}
