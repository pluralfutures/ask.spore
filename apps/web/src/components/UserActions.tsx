import { useState } from "react";

import type { AdminUser } from "../api/types";

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
        <button
          type="button"
          disabled={busy}
          className="rounded bg-red-700 px-2 text-white disabled:opacity-50"
          onClick={() => {
            setConfirming(false);
            onRemove();
          }}
        >
          Remove {user.email}
        </button>
        <button type="button" className="underline" onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-2">
      {canResend ? (
        <button type="button" disabled={busy} className="underline" onClick={onResend}>
          Resend invitation
        </button>
      ) : null}
      {canRemove ? (
        <button type="button" className="underline" onClick={() => setConfirming(true)}>
          Remove
        </button>
      ) : null}
    </span>
  );
}
