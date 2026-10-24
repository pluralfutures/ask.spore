import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ConversationCreated } from "../api/types";
import { StartPanel } from "../components/StartPanel";
import { keepsNoHistory } from "../lib/noHistory";
import { createBody, initialChoice, refusalText, type StartChoice } from "../lib/startPanel";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";
import { Textarea } from "../ui/Input";
import { Notice } from "../ui/Notice";
import { Loading } from "../ui/States";
import { EmptyState } from "../ui/States";

// What the chat page needs from the start: the first question, the spend-cap notice, and,
// for a tenant that keeps no history (P1b-14), the conversation itself, which no read
// route returns.
export interface StartState {
  question: string;
  notice: string | null;
  conversation?: ConversationCreated | null;
}

// P1a-12: the conversation is created with its first question, so the panel's choice
// stays editable until that first message and is fixed from then on.
export function NewConversation() {
  const navigate = useNavigate();
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.workspaces });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const [edited, setEdited] = useState<StartChoice | null>(null);
  const [question, setQuestion] = useState("");
  const create = useMutation({
    mutationFn: (choice: StartChoice) => api.createConversation(createBody(choice)),
    onSuccess: (created) => {
      const state: StartState = {
        question: question.trim(),
        notice: created.notice_text ?? null,
        conversation: keepsNoHistory(created) ? created : null,
      };
      navigate(`/c/${created.id}`, { state });
    },
  });

  if (workspaces.isPending || models.isPending) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <Loading />
      </main>
    );
  }
  if (!workspaces.data || !models.data) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <Notice tone="danger">Could not load the options.</Notice>
      </main>
    );
  }
  const choice = edited ?? initialChoice(workspaces.data, models.data);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim()) create.mutate(choice);
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
      <Link to="/" className={`text-ui ${LINK}`}>
        ← Conversations
      </Link>
      {workspaces.data.length === 0 ? (
        <EmptyState title="No workspace has been set up for your organisation yet." />
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <StartPanel
            workspaces={workspaces.data}
            models={models.data}
            choice={choice}
            onChange={setEdited}
          />
          <label htmlFor="first-question" className="sr-only">
            Question
          </label>
          <Textarea
            id="first-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={4000}
            rows={3}
            placeholder="Ask a question about this workspace's sources"
          />
          {create.error ? (
            <Notice tone="danger" role="alert">
              {refusalText(create.error instanceof ApiError ? create.error.code : null)}
            </Notice>
          ) : null}
          <Button
            variant="primary"
            className="self-end"
            type="submit"
            disabled={create.isPending || !question.trim() || !choice.model}
          >
            Start
          </Button>
        </form>
      )}
    </main>
  );
}
