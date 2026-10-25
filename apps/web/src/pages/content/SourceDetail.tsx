import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { ContentSourceDetail, SourceRef } from "../../api/types";
import { canEdit, canReview, errorMessage, historyLine, timerText } from "../../lib/content";
import { formatDate } from "../../lib/format";
import { Button } from "../../ui/Button";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input, Textarea } from "../../ui/Input";
import { Checkbox, Radio } from "../../ui/Checkbox";
import { Notice } from "../../ui/Notice";
import { Skeleton } from "../../ui/States";
import { cardClass } from "../../ui/cardClass";
import { StatusBadge } from "../../ui/Badge";
import { Card } from "../../ui/Card";

// One source: its register metadata, history, jobs, ingestion status and errors, the
// licence file, links to its documents in the private RAGFlow UI, and the reviewer's
// actions (P1b-05). No document text: titles and metadata only.
export function SourceDetail({ roles }: { roles: string[] }) {
  const { id = "" } = useParams();
  const source = useQuery({
    queryKey: ["content", "source", id],
    queryFn: () => contentApi.source(id),
  });
  if (source.error) return <Notice tone="danger">{errorMessage(source.error)}</Notice>;
  if (!source.data) return <Skeleton />;
  return (
    <section className="flex flex-col gap-4">
      <SourceSummary source={source.data} />
      {canReview(roles) ? <ReviewActions source={source.data} /> : null}
      {canEdit(roles) || canReview(roles) ? <LicenceUpload id={source.data.id} /> : null}
      <SourceRecord source={source.data} />
    </section>
  );
}

export function SourceSummary({ source }: { source: ContentSourceDetail }) {
  return (
    <Card title={source.title}>
      {/* UX-21: the source's facts as a definition list. */}
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-[max-content_minmax(0,1fr)]">
        <Fact label="Publisher">{source.publisher}</Fact>
        <Fact label="Type">{source.type.toUpperCase()}</Fact>
        <Fact label="Published">{formatDate(source.published_on)}</Fact>
        <Fact label="Tags">{source.tags.join(", ")}</Fact>
        <Fact label="Status">
          <StatusBadge kind="source" status={source.status} data-testid="source-status" />
          {source.chunk_count !== null ? ` · ${source.chunk_count} chunks` : ""}
          {source.downloadable ? " · downloadable" : ""}
        </Fact>
        <Fact label="Licence basis">{source.licence_basis}</Fact>
        {source.canonical_url ? (
          <Fact label="Canonical link">
            <a
              href={source.canonical_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`[overflow-wrap:anywhere] ${LINK}`}
            >
              {source.canonical_url}
            </a>
          </Fact>
        ) : null}
        <Fact label="Licence file">
          {source.licence_file ? (
            <a href={contentApi.licenceUrl(source.id)} className={LINK}>
              Licence or permission letter
            </a>
          ) : (
            <span className="text-fg-muted">No licence file on record.</span>
          )}
        </Fact>
        {source.review_note ? <Fact label="Reviewer's note">{source.review_note}</Fact> : null}
        {source.withdrawal_reason ? (
          <Fact label="Withdrawn">
            {formatDate(source.withdrawn_at)}: {source.withdrawal_reason}
          </Fact>
        ) : null}
        {source.status === "paused" ? (
          <Fact label="Paused">
            <span data-testid="pause-record">
              {formatDate(source.paused_at)}
              {source.paused_by ? ` by ${source.paused_by}` : ""}: {source.pause_reason}
            </span>
          </Fact>
        ) : null}
        {source.supersedes ? <Fact label="Replaces">{source.supersedes.title}</Fact> : null}
      </dl>
      {source.error ? (
        <Notice tone="danger" data-testid="source-error">
          Ingestion error: {source.error}
        </Notice>
      ) : null}
      {source.possible_replacements.length ? (
        <Notice tone="warning" data-testid="possible-replacement">
          Possible replacement of{" "}
          {source.possible_replacements.map((r) => `${r.title} (${r.publisher})`).join("; ")}
        </Notice>
      ) : null}
      {source.takedown ? (
        <Notice tone="danger" data-testid="takedown">
          Takedown {source.takedown.reference}, requested {formatDate(source.takedown.requested_on)}
          , due {formatDate(source.takedown.due_on)}
          {source.status === "withdrawn"
            ? ""
            : ` (${timerText(source.takedown.working_days_left)})`}
          {source.takedown.licence_grounds ? " · licence grounds" : ""}
        </Notice>
      ) : null}
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="mb-1 sm:mb-0">{children}</dd>
    </>
  );
}

export function SourceRecord({ source }: { source: ContentSourceDetail }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title="Documents in RAGFlow" level={3}>
        {source.documents.length === 0 ? <p className="text-fg-muted">None.</p> : null}
        <ul>
          {source.documents.map((d) => (
            <li key={d.dataset_id}>
              {d.tag}:{" "}
              {d.ragflow_url ? (
                <a href={d.ragflow_url} target="_blank" rel="noopener noreferrer" className={LINK}>
                  chunks in the RAGFlow UI
                </a>
              ) : (
                d.document_id
              )}
            </li>
          ))}
        </ul>
        {source.documents.some((d) => d.ragflow_url) ? (
          <p className="text-meta text-fg-muted">
            The RAGFlow UI is private: it opens over an SSH tunnel to the Instance (operators only).
          </p>
        ) : null}
        <h3 className="text-heading font-strong">Jobs</h3>
        <ul>
          {source.jobs.map((job) => (
            <li key={job.id}>
              {job.type} · <StatusBadge kind="job" status={job.status} />
              {job.error_code ? ` · ${job.error_code}` : ""} · {formatDate(job.created_at)}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="History" level={3}>
        <ol>
          {source.history.map((entry, n) => (
            <li key={n}>
              {formatDate(entry.at)} · {historyLine(entry)}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function ReviewActions({ source }: { source: ContentSourceDetail }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["content"] });
  const [note, setNote] = useState("");
  const [choice, setChoice] = useState<string>("");
  const [reason, setReason] = useState("");
  const approve = useMutation({
    mutationFn: () =>
      contentApi.approve(source.id, {
        note: note.trim() || null,
        replaces: choice && choice !== "keep" ? choice : null,
        keep_both: choice === "keep",
      }),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: () => contentApi.reject(source.id, note),
    onSuccess: refresh,
  });
  const retry = useMutation({ mutationFn: () => contentApi.retry(source.id), onSuccess: refresh });
  const withdraw = useMutation({
    mutationFn: () => contentApi.withdraw(source.id, reason),
    onSuccess: refresh,
  });
  const restore = useMutation({
    mutationFn: () => contentApi.restore(source.id),
    onSuccess: refresh,
  });
  // P2A-04: pause and resume, done in the call (the RAGFlow documents are switched).
  const [pauseReason, setPauseReason] = useState("");
  const pause = useMutation({
    mutationFn: () => contentApi.pause(source.id, pauseReason),
    onSuccess: async () => {
      setPauseReason("");
      await refresh();
    },
  });
  const resume = useMutation({
    mutationFn: () => contentApi.resume(source.id),
    onSuccess: refresh,
  });
  const error =
    errorMessage(approve.error) ??
    errorMessage(reject.error) ??
    errorMessage(retry.error) ??
    errorMessage(withdraw.error) ??
    errorMessage(restore.error) ??
    errorMessage(pause.error) ??
    errorMessage(resume.error);
  return (
    <Card title="Review" level={3}>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {source.status === "proposed" ? (
        <div className="flex flex-col gap-2">
          {source.possible_replacements.length ? (
            <ReplacementChoice
              candidates={source.possible_replacements}
              value={choice}
              onChange={setChoice}
            />
          ) : null}
          <Field label="Note (required to reject)">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button
              variant="primary"
              onClick={() => approve.mutate()}
              disabled={approve.isPending || (source.possible_replacements.length > 0 && !choice)}
            >
              Approve
            </Button>
            <Button
              variant="secondary"
              onClick={() => reject.mutate()}
              disabled={reject.isPending || !note.trim()}
            >
              Reject
            </Button>
          </div>
        </div>
      ) : null}
      {source.status === "failed" ? (
        <Button variant="secondary" className="w-fit" onClick={() => retry.mutate()}>
          Retry ingestion
        </Button>
      ) : null}
      <PauseControls
        status={source.status}
        reason={pauseReason}
        onReason={setPauseReason}
        onPause={() => pause.mutate()}
        onResume={() => resume.mutate()}
        pending={pause.isPending || resume.isPending}
      />
      {source.status === "ingested" || source.status === "paused" || source.status === "failed" ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Withdrawal reason">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            variant="secondary-danger"
            onClick={() => withdraw.mutate()}
            disabled={withdraw.isPending || !reason.trim()}
          >
            Withdraw everywhere
          </Button>
        </div>
      ) : null}
      {source.status === "withdrawn" && source.site_id ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            className="w-fit"
            onClick={() => restore.mutate()}
            disabled={restore.isPending || restore.isSuccess}
          >
            Restore page
          </Button>
          <span className="text-fg-muted">
            {restore.isSuccess
              ? "Restored: the next crawl of the site takes it again."
              : "The next crawl of its site takes the page again as a new version."}
          </span>
        </div>
      ) : null}
      {source.status !== "withdrawn" ? <TakedownForm id={source.id} /> : null}
    </Card>
  );
}

// P2A-04: "Pause" with a reason on an ingested source, "Resume" on a paused one.
export function PauseControls({
  status,
  reason,
  onReason,
  onPause,
  onResume,
  pending,
}: {
  status: string;
  reason: string;
  onReason: (reason: string) => void;
  onPause: () => void;
  onResume: () => void;
  pending: boolean;
}) {
  if (status === "paused")
    return (
      <Button variant="secondary" className="w-fit" onClick={onResume} disabled={pending}>
        Resume
      </Button>
    );
  if (status !== "ingested") return null;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="Pause reason">
        <Input value={reason} onChange={(e) => onReason(e.target.value)} />
      </Field>
      <Button variant="secondary" onClick={onPause} disabled={pending || !reason.trim()}>
        Pause
      </Button>
      <span className="text-meta text-fg-muted">
        Out of retrieval, file lists and downloads for every tenant until resumed. A pause does not
        answer a takedown.
      </span>
    </div>
  );
}

// Owner decision 4 (Oct 22, 2026): the reviewer chooses replace or keep both.
export function ReplacementChoice({
  candidates,
  value,
  onChange,
}: {
  candidates: SourceRef[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-warning">
        Possible replacement: this file is at the canonical link of an ingested source.
      </legend>
      {candidates.map((c) => (
        <Radio
          key={c.id}
          name="replacement"
          value={c.id}
          checked={value === c.id}
          onChange={() => onChange(c.id)}
        >
          Replace {c.title} ({c.publisher})
        </Radio>
      ))}
      <Radio
        name="replacement"
        value="keep"
        checked={value === "keep"}
        onChange={() => onChange("keep")}
      >
        Keep both
      </Radio>
    </fieldset>
  );
}

function TakedownForm({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const [reference, setReference] = useState("");
  const [requestedOn, setRequestedOn] = useState("");
  const [breach, setBreach] = useState(false);
  const [grounds, setGrounds] = useState(false);
  const record = useMutation({
    mutationFn: () =>
      contentApi.takedown(id, {
        reference: reference.trim(),
        requested_on: requestedOn,
        licence_breach: breach,
        licence_grounds: grounds || breach,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content"] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    record.mutate();
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 border-t pt-2">
      <span className="w-full font-strong">Record a takedown request</span>
      <Field label="Reference">
        <Input value={reference} onChange={(e) => setReference(e.target.value)} required />
      </Field>
      <Field label="Requested on">
        <Input
          type="date"
          value={requestedOn}
          onChange={(e) => setRequestedOn(e.target.value)}
          required
        />
      </Field>
      <Checkbox checked={breach} onChange={(e) => setBreach(e.target.checked)}>
        Licence breach we found (due today)
      </Checkbox>
      <Checkbox
        checked={grounds || breach}
        disabled={breach}
        onChange={(e) => setGrounds(e.target.checked)}
      >
        On licence grounds
      </Checkbox>
      <Button variant="secondary" type="submit" disabled={record.isPending}>
        Record
      </Button>
      {errorMessage(record.error) ? (
        <Notice tone="danger" className="w-full">
          {errorMessage(record.error)}
        </Notice>
      ) : null}
    </form>
  );
}

function LicenceUpload({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("licence_file", file);
      return contentApi.attachLicence(id, form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content", "source", id] }),
  });
  return (
    <div className={cardClass("flex flex-wrap items-end gap-2")}>
      <Field label="Licence or permission letter (PDF, DOCX, TXT, EML, image)">
        <Input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Button
        variant="secondary"
        onClick={() => upload.mutate()}
        disabled={!file || upload.isPending}
      >
        Attach
      </Button>
      {errorMessage(upload.error) ? (
        <Notice tone="danger">{errorMessage(upload.error)}</Notice>
      ) : null}
    </div>
  );
}
