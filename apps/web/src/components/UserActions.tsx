import { useState } from "react";

import type { AdminUser } from "../api/types";
import { Button } from "../ui/Button";

// P1c-07: "Resend invitation" for a user still invited, and "Remove" with a confirmation
// in place (the user's account data and history are deleted; the audit trail stays).
// Shared by the tenant admin page and the operator console's users tab.
export function UserActions({
  user,
  canResend,
  canRemove,
  onResend,
  onRemove,
  busy,
}: {
  user: AdminUser;
  canResend: boolean;
  canRemove: boolean;
  onResend: () => void;
  onRemove: () => void;
  busy: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <span className="flex flex-wrap items-center gap-2" role="group" aria-label="Confirm removal">
        <span>Remove {user.email} and delete their conversations?</span>
        <Button
          variant="danger"
          size="sm"
          disabled={busy}
          onClick={() => {
            setConfirming(false);
            onRemove();
          }}
        >
          Remove {user.email}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          Cancel
        </Button>
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-2">
      {canResend ? (
        <Button variant="ghost" size="sm" disabled={busy} onClick={onResend}>
          Resend invitation
        </Button>
      ) : null}
      {canRemove ? (
        <Button variant="ghost-danger" size="sm" onClick={() => setConfirming(true)}>
          Remove
        </Button>
      ) : null}
    </span>
  );
}
