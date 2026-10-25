import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "./Button";

// UX-09: a modal confirmation on the native <dialog>: the rest of the page is inert while
// it is open (the focus trap), Escape cancels, and focus returns to the control that
// opened it; Tab wraps from the last control to the first. Replaces window.confirm and
// the in-row confirmations.
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  busy = false,
}: {
  open: boolean;
  title: ReactNode;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) {
      opener.current = document.activeElement as HTMLElement | null;
      node.showModal();
    } else if (!open && node.open) {
      node.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClose={() => opener.current?.focus()}
      onKeyDown={(event) => {
        // Tab wraps inside the dialog instead of leaving for the browser's own controls.
        if (event.key !== "Tab") return;
        const focusable = [
          ...event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), [href]"),
        ];
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-dialog border bg-surface p-0 text-fg shadow-overlay backdrop:bg-fg/40"
    >
      {open ? (
        <div className="flex flex-col gap-4 p-5">
          <h2 id={titleId} className="text-heading font-strong">
            {title}
          </h2>
          {children ? <div className="text-ui text-fg-secondary">{children}</div> : null}
          <div className="flex flex-wrap justify-end gap-2">
            {/* Cancel first and focused: the safe choice is the default one. */}
            <Button autoFocus onClick={onCancel}>
              {cancelLabel}
            </Button>
            <Button variant="danger" disabled={busy} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
