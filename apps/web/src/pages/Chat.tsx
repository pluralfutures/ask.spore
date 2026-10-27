import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useRef, useState, type ComponentProps, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Citation, DoneData } from "../api/types";
import { AssistantMessage } from "../components/AssistantMessage";
import { answerNote, hasBody, PARTIAL_NOTE } from "../lib/answerNotes";
import { failoverNote } from "../lib/failover";
import { NO_HISTORY_NOTE, sameChoice } from "../lib/noHistory";
import { CitationPanel } from "../components/CitationPanel";
import { ConversationHeader } from "../components/ConversationHeader";
import { RenameTitle } from "../components/RenameTitle";
import type { StartState } from "../components/StartForm";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { LINK } from "../ui/link";
import { Textarea } from "../ui/Input";
import { Notice } from "../ui/Notice";
import { Loading } from "../ui/States";
import { CONVERSATIONS_PATH } from "./ConversationList";

interface Live {
  question: string;
  text: string;
  citations: Citation[];
  done: DoneData | null;
  error: string | null;
  // P1c-09: the user pressed "Stop"; the server keeps what was shown, flagged partial.
  stopped?: boolean;
}

interface Selection {
  key: string; // message id, or "live"
  marker: number;
}

const ERRORS: Record<string, string> = {
  retrieval_unavailable: "The research library is unavailable. Try again shortly.",
  conversation_gone: "This conversation was deleted.",
  spend_cap_reached:
    "This month's budget for models served outside the EU has been used up. " +
    "Start a new conversation to continue with another model.",
  model_unavailable: "This conversation's model is not available right now.",
  model_not_enabled: "This conversation's model is no longer enabled for your organisation.",
  external_not_entitled: "This conversation's model is no longer enabled for your organisation.",
  answer_cut_off:
    "The model used its whole length budget before it could answer. Ask again, or start a " +
    "new conversation with reasoning off.",
};

// After a stop or a failed answer, the server stores the partial turn when it notices the
// closed stream: the conversation is reloaded until it holds the turn (or gives up).
const SETTLE_TRIES = 6;

// UX-15: the user's question as a bubble on the right, at most 80% wide.
const QUESTION =
  "max-w-[80%] self-end rounded-card bg-neutral-muted px-3.5 py-2.5 [overflow-wrap:anywhere]";
const SETTLE_DELAY_MS = 400;

export function Chat() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  // From the start panel (P1a-12): the first question, sent once, and the spend-cap
  // fallback notice, kept for this visit.
  const location = useLocation();
  const navigate = useNavigate();
  const [start] = useState<StartState | null>(() => location.state as StartState | null);
  // P1b-14: a tenant that keeps no history. Its conversations take one question each and
  // are never readable, so this visit's turns live here only.
  const noHistory = start?.conversation?.no_history ? start.conversation : null;
  const conversation = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api.getConversation(id),
    enabled: noHistory === null,
  });
  const [past, setPast] = useState<Live[]>([]);
  const used = useRef(false); // the current no-history conversation took its question
  const [question, setQuestion] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  // P2B-03: renaming the open conversation from its header.
  const [renaming, setRenaming] = useState(false);
  const [renamed, setRenamed] = useState("");
  const refocus = useRef(false); // focus returns to the Rename button once it is back
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || (live && !live.done && !live.error)) return;
    setQuestion("");
    await send(text);
  }

  function stop() {
    abort.current?.abort();
  }

  // The partial turn the server kept after a stop or a failure: once the reloaded
  // conversation has it, the live copy goes (P1c-09).
  async function settle(before: number) {
    for (let i = 0; i < SETTLE_TRIES; i++) {
      const { data } = await conversation.refetch();
      if ((data?.messages.length ?? 0) > before) {
        setLive(null);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, SETTLE_DELAY_MS));
    }
    await queryClient.invalidateQueries({ queryKey: ["conversations"] });
  }

  async function send(text: string) {
    setSelection(null);
    const before = conversation.data?.messages.length ?? 0;
    const state: Live = { question: text, text: "", citations: [], done: null, error: null };
    setLive(state);
    abort.current = new AbortController();
    let target = id;
    try {
      if (noHistory) {
        // Each question after the first starts a new one-question conversation.
        if (used.current) target = (await api.createConversation(sameChoice(noHistory))).id;
        used.current = true;
      }
      for await (const e of api.ask(target, text, abort.current.signal)) {
        if (e.event === "token") state.text += e.data.text;
        else if (e.event === "citations") state.citations = e.data.citations;
        else if (e.event === "done") state.done = e.data;
        else state.error = ERRORS[e.data.error_code] ?? "The answer could not be completed.";
        setLive({ ...state });
      }
    } catch {
      if (abort.current?.signal.aborted) state.stopped = true;
      else state.error = "The answer could not be completed.";
      setLive({ ...state });
      if (state.stopped && !noHistory) await settle(before);
      return;
    }
    if (noHistory) {
      // Nothing to reload: the answer is gone from the server once it ends.
      setPast((turns) => [...turns, { ...state }]);
      setLive(null);
      return;
    }
    if (state.error && !noHistory) {
      // A model that failed mid-stream leaves the partial turn stored; show that one.
      await settle(before);
      return;
    }
    if (state.done) {
      // The live answer stays on screen until the reloaded conversation holds it. A load
      // still in flight was made before the answer (and its title) existed: drop it, so a
      // late response cannot replace the reload (P2B-04).
      await queryClient.cancelQueries({ queryKey: ["conversation", id] });
      await queryClient.refetchQueries({ queryKey: ["conversation", id] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }
  }

  useEffect(() => {
    if (!start?.question) return;
    // A timer, so StrictMode's mount, unmount and mount sends the question once; the
    // state is dropped so a reload does not ask it again.
    const timer = setTimeout(() => {
      navigate(location.pathname, { replace: true, state: null });
      void send(start.question);
    }, 0);
    return () => clearTimeout(timer);
    // Once per visit: the start state never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);

  const messages = conversation.data?.messages ?? [];
  const citationsFor = (key: string): Citation[] => {
    if (key === "live") return live?.citations ?? [];
    if (key.startsWith("past-")) return past[Number(key.slice(5))]?.citations ?? [];
    return messages.find((m) => m.id === key)?.citations ?? [];
  };
  const busy = live !== null && !live.done && !live.error;
  const persisted = live?.done ? messages.some((m) => m.id === live.done?.message_id) : false;

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="mx-auto flex w-full max-w-[47.5rem] min-w-0 flex-1 flex-col px-4 pt-4 md:px-8 md:pt-6">
        <header className="mb-6 flex flex-col gap-2 border-b pb-4">
          <Link to={CONVERSATIONS_PATH} className={`w-fit text-ui ${LINK}`}>
            ← Conversations
          </Link>
          {renaming && conversation.data ? (
            <RenameTitle
              conversationId={id}
              current={conversation.data.title ?? ""}
              onDone={(saved) => {
                setRenaming(false);
                refocus.current = true;
                if (saved) setRenamed(`Renamed to ${saved}.`);
              }}
            />
          ) : (
            <div className="flex items-start gap-2">
              <h1 className="min-w-0 text-heading font-strong [overflow-wrap:anywhere]">
                {conversation.data?.title ?? "New conversation"}
              </h1>
              {conversation.data && !noHistory ? (
                <IconButton
                  ref={(button) => {
                    if (button && refocus.current) {
                      refocus.current = false;
                      button.focus();
                    }
                  }}
                  label="Rename this conversation"
                  icon={Pencil}
                  size="sm"
                  onClick={() => setRenaming(true)}
                />
              ) : null}
            </div>
          )}
          <p aria-live="polite" className="sr-only">
            {renamed}
          </p>
          {conversation.data ? <ConversationHeader conversation={conversation.data} /> : null}
          {noHistory ? <Notice data-testid="no-history">{NO_HISTORY_NOTE}</Notice> : null}
          {start?.notice ? (
            <Notice tone="warning" role="status">
              {start.notice}
            </Notice>
          ) : null}
        </header>
        {conversation.isError && !noHistory ? (
          <Notice tone="danger">Conversation not found.</Notice>
        ) : null}
        <ol className="flex flex-col gap-6">
          {past.map((turn, i) => (
            <PastTurn
              key={`past-${i}`}
              turn={turn}
              onCite={(marker) => setSelection({ key: `past-${i}`, marker })}
            />
          ))}
          {messages.map((m) =>
            m.role === "user" ? (
              <li key={m.id} className={QUESTION}>
                {m.content}
              </li>
            ) : (
              <li key={m.id}>
                <Answer
                  body={hasBody(m.content, m)}
                  text={m.content}
                  citations={m.citations}
                  unsupported={m.unsupported && !m.partial}
                  abstained={m.abstained}
                  messageId={m.id}
                  onCite={(marker) => setSelection({ key: m.id, marker })}
                  note={answerNote(m)}
                  failover={m.failover}
                />
              </li>
            ),
          )}
          {live && !persisted ? (
            <>
              <li className={QUESTION}>{live.question}</li>
              <li aria-live="polite">
                {live.text || live.done || live.stopped || live.error ? (
                  <Answer
                    body={!!(live.text || live.done)}
                    text={live.text}
                    citations={live.citations}
                    unsupported={live.done?.unsupported ?? false}
                    abstained={live.done?.abstained ?? false}
                    messageId={noHistory ? null : (live.done?.message_id ?? null)}
                    onCite={(marker) => setSelection({ key: "live", marker })}
                    note={
                      live.stopped ? PARTIAL_NOTE : answerNote({ truncated: live.done?.truncated })
                    }
                    failover={live.done?.failover}
                  />
                ) : (
                  <Loading>Searching your research package…</Loading>
                )}
                {live.error ? (
                  <Notice tone="danger" className="mt-2">
                    {live.error}
                  </Notice>
                ) : null}
              </li>
            </>
          ) : null}
        </ol>
        {/* UX-15: the composer stays at the bottom of the screen while the thread scrolls. */}
        <form
          onSubmit={ask}
          className="sticky bottom-0 -mx-4 mt-auto flex items-end gap-2 border-t bg-canvas px-4 pt-4 pb-4 md:-mx-8 md:px-8 md:pb-6"
        >
          <label htmlFor="question" className="sr-only">
            Question
          </label>
          <Textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={4000}
            rows={2}
            placeholder="Ask a question about your research package"
            className="min-w-0 flex-1 bg-surface"
          />
          {busy ? (
            <Button variant="secondary" onClick={stop}>
              Stop
            </Button>
          ) : (
            <Button variant="primary" type="submit" disabled={!question.trim()}>
              Ask
            </Button>
          )}
        </form>
      </div>
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

// A no-history turn of this visit (P1b-14): shown as answered, with no feedback, since
// the message no longer exists on the server.
function PastTurn({ turn, onCite }: { turn: Live; onCite: (marker: number) => void }) {
  return (
    <>
      <li className={QUESTION}>{turn.question}</li>
      <li>
        <Answer
          body={!!(turn.text || turn.done)}
          text={turn.text}
          citations={turn.citations}
          unsupported={turn.done?.unsupported ?? false}
          abstained={turn.done?.abstained ?? false}
          messageId={null}
          onCite={onCite}
          note={turn.stopped ? PARTIAL_NOTE : answerNote({ truncated: turn.done?.truncated })}
          failover={turn.done?.failover}
        />
        {turn.error ? (
          <Notice tone="danger" className="mt-2">
            {turn.error}
          </Notice>
        ) : null}
      </li>
    </>
  );
}

// An answer with its notes inside the block (UX-15); a turn with no text (stopped before
// any token) shows the notes on their own.
function Answer({
  body,
  note,
  failover,
  ...message
}: Omit<ComponentProps<typeof AssistantMessage>, "notes"> & {
  body: boolean;
  note: string | null;
  failover: "eu" | "external" | null | undefined;
}) {
  const notes =
    note || failoverNote(failover) ? (
      <div className="flex flex-col gap-1">
        <AnswerNote note={note} />
        <FailoverNote kind={failover} />
      </div>
    ) : null;
  return body ? <AssistantMessage {...message} notes={notes} /> : notes;
}

function AnswerNote({ note }: { note: string | null }) {
  return note ? (
    <p data-testid="answer-note" className="text-ui text-warning">
      {note}
    </p>
  ) : null;
}

function FailoverNote({ kind }: { kind: "eu" | "external" | null | undefined }) {
  const note = failoverNote(kind);
  return note ? (
    <p data-testid="failover" className="text-ui text-fg-muted">
      {note}
    </p>
  ) : null;
}
