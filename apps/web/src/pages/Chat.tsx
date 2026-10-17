import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Citation, DoneData } from "../api/types";
import { AssistantMessage } from "../components/AssistantMessage";
import { CitationPanel } from "../components/CitationPanel";
import { formatDate } from "../lib/format";

interface Live {
  question: string;
  text: string;
  citations: Citation[];
  done: DoneData | null;
  error: string | null;
}

interface Selection {
  key: string; // message id, or "live"
  marker: number;
}

const ERRORS: Record<string, string> = {
  retrieval_unavailable: "The research library is unavailable. Try again shortly.",
  conversation_gone: "This conversation was deleted.",
};

export function Chat() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const conversation = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api.getConversation(id),
  });
  const [question, setQuestion] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || (live && !live.done && !live.error)) return;
    setQuestion("");
    setSelection(null);
    const state: Live = { question: text, text: "", citations: [], done: null, error: null };
    setLive(state);
    abort.current = new AbortController();
    try {
      for await (const e of api.ask(id, text, abort.current.signal)) {
        if (e.event === "token") state.text += e.data.text;
        else if (e.event === "citations") state.citations = e.data.citations;
        else if (e.event === "done") state.done = e.data;
        else state.error = ERRORS[e.data.error_code] ?? "The answer could not be completed.";
        setLive({ ...state });
      }
    } catch {
      state.error = "The answer could not be completed.";
      setLive({ ...state });
      return;
    }
    if (state.done) {
      await queryClient.invalidateQueries({ queryKey: ["conversation", id] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setLive(null);
    }
  }

  const messages = conversation.data?.messages ?? [];
  const citationsFor = (key: string): Citation[] =>
    key === "live"
      ? (live?.citations ?? [])
      : (messages.find((m) => m.id === key)?.citations ?? []);
  const busy = live !== null && !live.done && !live.error;

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <main className="mx-auto flex w-full max-w-3xl min-w-0 flex-1 flex-col p-4">
        <header className="mb-4">
          <Link to="/" className="text-sm underline">
            ← Conversations
          </Link>
          <h1 className="text-lg font-semibold">
            {conversation.data?.title ?? "New conversation"}
          </h1>
          {conversation.data ? (
            <p className="text-sm text-slate-600">
              Expires {formatDate(conversation.data.expires_at)}
            </p>
          ) : null}
        </header>
        {conversation.isError ? <p className="text-red-700">Conversation not found.</p> : null}
        <ol className="flex flex-col gap-3">
          {messages.map((m) =>
            m.role === "user" ? (
              <li key={m.id} className="self-end rounded bg-slate-200 px-3 py-2">
                {m.content}
              </li>
            ) : (
              <li key={m.id}>
                <AssistantMessage
                  text={m.content}
                  citations={m.citations}
                  unsupported={m.unsupported}
                  abstained={m.abstained}
                  messageId={m.id}
                  onCite={(marker) => setSelection({ key: m.id, marker })}
                />
              </li>
            ),
          )}
          {live ? (
            <>
              <li className="self-end rounded bg-slate-200 px-3 py-2">{live.question}</li>
              <li aria-live="polite">
                {live.text || live.done ? (
                  <AssistantMessage
                    text={live.text}
                    citations={live.citations}
                    unsupported={live.done?.unsupported ?? false}
                    abstained={live.done?.abstained ?? false}
                    messageId={live.done?.message_id ?? null}
                    onCite={(marker) => setSelection({ key: "live", marker })}
                  />
                ) : (
                  <p className="text-slate-600">Searching your research package…</p>
                )}
                {live.error ? <p className="mt-2 text-red-700">{live.error}</p> : null}
              </li>
            </>
          ) : null}
        </ol>
        <form onSubmit={ask} className="mt-auto flex gap-2 pt-4">
          <label htmlFor="question" className="sr-only">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={4000}
            rows={2}
            placeholder="Ask a question about your research package"
            className="flex-1 rounded border px-2 py-1"
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </main>
      {selection ? (
        <CitationPanel
          citations={citationsFor(selection.key)}
          selected={selection.marker}
          onClose={() => setSelection(null)}
        />
      ) : null}
    </div>
  );
}
