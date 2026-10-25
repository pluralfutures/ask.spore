import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ConversationCreated } from "../api/types";
import { StartPanel } from "../components/StartPanel";
import { keepsNoHistory } from "../lib/noHistory";
import { createBody, initialChoice, refusalText, type StartChoice } from "../lib/startPanel";
import { Button } from "../ui/Button";
import { LINK } from "../ui/link";
import { Field } from "../ui/Field";
import { Textarea } from "../ui/Input";
import { Notice } from "../ui/Notice";
import { EmptyState, Skeleton } from "../ui/States";

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
      <StartPage>
        <Skeleton />
      </StartPage>
    );
  }
  if (!workspaces.data || !models.data) {
    return (
      <StartPage>
        <Notice tone="danger">Could not load the options.</Notice>
      </StartPage>
    );
  }
  const choice = edited ?? initialChoice(workspaces.data, models.data);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim()) create.mutate(choice);
  }

  return (
    <StartPage>
      {workspaces.data.length === 0 ? (
        <EmptyState title="No workspace has been set up for your organisation yet." />
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-6">
          {/* UX-14 (mockup 2): the question first, with a visible label, then the settings. */}
          <Field label="Question">
            <Textarea
              id="first-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={4000}
              rows={5}
              placeholder="Ask a question about this workspace's sources"
            />
          </Field>
          <StartPanel
            workspaces={workspaces.data}
            models={models.data}
            choice={choice}
            onChange={setEdited}
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
    </StartPage>
  );
}

// Every state of the start page (loading, error, no workspace, the form) has the back link
// and the page's h1, the former legend of the panel.
function StartPage({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 md:px-8 md:py-6">
      <Link to="/" className={`w-fit text-ui ${LINK}`}>
        ← Conversations
      </Link>
      <h1 className="text-title font-strong">New conversation</h1>
      {children}
    </div>
  );
}
