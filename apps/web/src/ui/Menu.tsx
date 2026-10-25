import { ChevronDown, MoreHorizontal } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cx } from "./controlClass";
import { buttonClass } from "./buttonClass";
import { IconButton } from "./IconButton";

// UX-09: the row-action menu: one "⋯" button per table row instead of stacked links.
// The list is positioned fixed under the button, so a table's scroll box cannot clip it,
// kept inside the viewport (above the button when there is no room below).
// Keyboard: the first item takes focus on open; arrow keys, Home and End move; Escape
// closes and returns focus to the button; Tab closes.

export interface MenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}

// `text`: a button showing that text and a chevron (the user menu) instead of "⋯"; its
// accessible name is then `label`.
export function Menu({
  label,
  items,
  text,
}: {
  label: string;
  items: MenuItem[];
  text?: ReactNode;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const open = place !== null;
  const MARGIN = 8;

  function measure() {
    const box = trigger.current?.getBoundingClientRect();
    if (!box) return;
    const width = list.current?.offsetWidth ?? 0;
    const height = list.current?.offsetHeight ?? 0;
    const below = box.bottom + 4;
    const top = below + height > window.innerHeight - MARGIN ? box.top - height - 4 : below;
    const left = Math.min(box.right - width, document.documentElement.clientWidth - width - MARGIN);
    setPlace({ top: Math.max(MARGIN, top), left: Math.max(MARGIN, left) });
  }

  // Once the list is drawn its size is known: place it again before the browser paints.
  useLayoutEffect(() => {
    if (open) measure();
  }, [open]);

  function close(returnFocus: boolean) {
    setPlace(null);
    if (returnFocus) trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLElement>("[role=menuitem]:not(:disabled)")?.focus();
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!list.current?.contains(target) && !trigger.current?.contains(target)) close(false);
    };
    document.addEventListener("pointerdown", away);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      document.removeEventListener("pointerdown", away);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const enabled = [
      ...(list.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not(:disabled)") ?? []),
    ];
    const at = enabled.indexOf(document.activeElement as HTMLElement);
    const go = (index: number) => {
      event.preventDefault();
      enabled[(index + enabled.length) % enabled.length]?.focus();
    };
    if (event.key === "ArrowDown") go(at + 1);
    else if (event.key === "ArrowUp") go(at - 1);
    else if (event.key === "Home") go(0);
    else if (event.key === "End") go(enabled.length - 1);
    else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") close(false);
  }

  if (items.length === 0) return null;
  return (
    <>
      {text ? (
        <button
          ref={trigger}
          type="button"
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          onClick={() => (open ? close(false) : measure())}
          className={buttonClass("ghost", "sm", "max-w-48")}
        >
          <span className="truncate">{text}</span>
          <ChevronDown size={16} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
        </button>
      ) : (
        <IconButton
          ref={trigger}
          label={label}
          icon={MoreHorizontal}
          size="sm"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          onClick={() => (open ? close(false) : measure())}
        />
      )}
      {open ? (
        <div
          id={id}
          ref={list}
          role="menu"
          aria-label={label}
          onKeyDown={onKeyDown}
          style={{ top: place.top, left: place.left }}
          className="fixed z-20 flex min-w-44 flex-col rounded-card border bg-surface p-1 shadow-popover"
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                close(true);
                item.onSelect();
              }}
              className={cx(
                "flex min-h-9 items-center rounded-control px-3 text-left text-ui whitespace-nowrap",
                "not-disabled:hover:bg-neutral-muted focus-visible:bg-neutral-muted",
                "disabled:cursor-not-allowed disabled:text-fg-muted max-sm:min-h-11",
                item.danger ? "text-danger" : "text-fg",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </>
  );
}
