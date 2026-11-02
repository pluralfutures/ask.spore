import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { api } from "../api/client";
import type { ConversationDetail } from "../api/types";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

export const TITLE_MAX = 120; // the API's limit (P2B-03)

// P2B-03: rename in place. Enter saves, Escape cancels; focus starts in the field with the
// title selected. The title is plain text, trimmed, 1 to 120 characters. After a save the
// lists and the open conversation show the new title; `onDone` closes the editor.
export function RenameTitle({
  conversationId,
  current,
  onDone,
  className,
}: {
  conversationId: string;
  current: string;
  onDone: (saved: string | null) => void;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(current);
  const rename = useMutation({
    mutationFn: (title: string) => api.renameConversation(conversationId, title),
    onSuccess: (saved) => {
      queryClient.setQueryData<ConversationDetail>(["conversation", conversationId], (old) =>
        old ? { ...old, title: saved.title } : old,
      );
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onDone(saved.title ?? null);
    },
  });

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  const trimmed = value.trim();
  const unchanged = trimmed === current.trim();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (rename.isPending) return;
    if (trimmed === "" || unchanged) {
      if (unchanged) onDone(null);
      return;
    }
    rename.mutate(trimmed);
  }

  function key(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onDone(null);
    }
  }

  return (
    <form onSubmit={submit} onKeyDown={key} className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          ref={input}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="Conversation title"
          aria-invalid={rename.isError ? true : undefined}
          aria-describedby={rename.isError ? "rename-error" : undefined}
          maxLength={TITLE_MAX}
          autoComplete="off"
          className="min-w-0 flex-1"
        />
        <Button type="submit" variant="primary" size="sm" disabled={rename.isPending || !trimmed}>
          Save
        </Button>
        <Button size="sm" onClick={() => onDone(null)} disabled={rename.isPending}>
          Cancel
        </Button>
      </div>
      {rename.isError ? (
        <p id="rename-error" role="alert" className="mt-1 text-ui text-danger">
          The title could not be saved. Try again.
        </p>
      ) : null}
    </form>
  );
}
