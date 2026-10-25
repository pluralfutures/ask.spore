import { useState } from "react";

import type { AdminUser } from "../api/types";
import { ConfirmDialog } from "../ui/Dialog";
import { Menu, type MenuItem } from "../ui/Menu";

// P1c-07: "Resend invitation" for a user still invited, and "Remove" after a confirmation
// (the user's account data and history are deleted; the audit trail stays). Shared by the
// tenant admin page and the operator console's users tab. UX-09: the actions sit in the
// row's menu, and the confirmation is a dialog with the same words.
export function UserActions({
  user,
  canResend,
  canRemove,
  onResend,
  onRemove,
  busy,
  before = [],
}: {
  user: AdminUser;
  canResend: boolean;
  canRemove: boolean;
  onResend: () => void;
  onRemove: () => void;
  busy: boolean;
  before?: MenuItem[];
}) {
  const [confirming, setConfirming] = useState(false);
  const items: MenuItem[] = [...before];
  if (canResend) items.push({ label: "Resend invitation", onSelect: onResend, disabled: busy });
  if (canRemove) items.push({ label: "Remove", onSelect: () => setConfirming(true), danger: true });
  return (
    <>
      <Menu label={`Actions for ${user.email}`} items={items} />
      <ConfirmDialog
        open={confirming}
        title={`Remove ${user.email} and delete their conversations?`}
        confirmLabel={`Remove ${user.email}`}
        busy={busy}
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          onRemove();
        }}
      />
    </>
  );
}
