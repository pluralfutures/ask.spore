import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { ContentSourceDetail, SourceRef } from "../../api/types";
import { canEdit, canReview, errorMessage, historyLine, timerText } from "../../lib/content";
import { formatDate } from "../../lib/format";

// One source: its register metadata, history, jobs, ingestion status and errors, the
// licence file, links to its documents in the private RAGFlow UI, and the reviewer's
// actions (P1b-05). No document text: titles and metadata only.
export function SourceDetail({ roles }: { roles: string[] }) {
  const { id = "" } = useParams();
  const source = useQuery({
    queryKey: ["content", "source", id],
    queryFn: () => contentApi.source(id),
  });
  if (source.error) return <p className="text-red-700">{errorMessage(source.error)}</p>;
  if (!source.data) return <p>Loading…</p>;
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
    <div className="flex flex-col gap-1 rounded bg-white p-3">
      <h2 className="text-lg font-semibold">{source.title}</h2>
      <p>
        {source.publisher} · {source.type.toUpperCase()} · {formatDate(source.published_on)} ·{" "}
        {source.tags.join(", ")}
      </p>
      <p>
        Status: <strong data-testid="source-status">{source.status}</strong>
        {source.chunk_count !== null ? ` · ${source.chunk_count} chunks` : ""}
        {source.downloadable ? " · downloadable" : ""}
      </p>
      <p>Licence basis: {source.licence_basis}</p>
      {source.canonical_url ? (
        <p>
          Canonical link:{" "}
          <a
            href={source.canonical_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            {source.canonical_url}
          </a>
        </p>
      ) : null}
      {source.licence_file ? (
        <p>
          <a href={contentApi.licenceUrl(source.id)} className="underline">
            Licence or permission letter
          </a>
        </p>
      ) : (
        <p className="text-slate-600">No licence file on record.</p>
      )}
      {source.error ? (
        <p data-testid="source-error" className="text-red-700">
          Ingestion error: {source.error}
        </p>
      ) : null}
      {source.review_note ? <p>Reviewer's note: {source.review_note}</p> : null}
      {source.withdrawal_reason ? (
        <p>
          Withdrawn {formatDate(source.withdrawn_at)}: {source.withdrawal_reason}
        </p>
      ) : null}
      {source.supersedes ? <p>Replaces: {source.supersedes.title}</p> : null}
      {source.possible_replacements.length ? (
        <p data-testid="possible-replacement" className="text-amber-900">
          Possible replacement of{" "}
          {source.possible_replacements.map((r) => `${r.title} (${r.publisher})`).join("; ")}
        </p>
      ) : null}
      {source.takedown ? (
        <p data-testid="takedown" className="text-red-700">
          Takedown {source.takedown.reference}, requested {formatDate(source.takedown.requested_on)}
          , due {formatDate(source.takedown.due_on)}
          {source.status === "withdrawn"
            ? ""
            : ` (${timerText(source.takedown.working_days_left)})`}
          {source.takedown.licence_grounds ? " · licence grounds" : ""}
        </p>
      ) : null}
    </div>
  );
}

export function SourceRecord({ source }: { source: ContentSourceDetail }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded bg-white p-3">
        <h3 className="font-semibold">Documents in RAGFlow</h3>
        {source.documents.length === 0 ? <p className="text-slate-600">None.</p> : null}
        <ul>
          {source.documents.map((d) => (
            <li key={d.dataset_id}>
              {d.tag}:{" "}
              {d.ragflow_url ? (
                <a
                  href={d.ragflow_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  chunks in the RAGFlow UI
                </a>
              ) : (
                d.document_id
              )}
            </li>
          ))}
        </ul>
        {source.documents.some((d) => d.ragflow_url) ? (
          <p className="text-xs text-slate-600">
            The RAGFlow UI is private: it opens over an SSH tunnel to the Instance (operators only).
          </p>
        ) : null}
        <h3 className="mt-3 font-semibold">Jobs</h3>
        <ul>
          {source.jobs.map((job) => (
            <li key={job.id}>
              {job.type} · {job.status}
              {job.error_code ? ` · ${job.error_code}` : ""} · {formatDate(job.created_at)}
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded bg-white p-3">
        <h3 className="font-semibold">History</h3>
        <ol>
          {source.history.map((entry, n) => (
            <li key={n}>
              {formatDate(entry.at)} · {historyLine(entry)}
            </li>
          ))}
        </ol>
      </div>
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
  const error =
    errorMessage(approve.error) ??
    errorMessage(reject.error) ??
    errorMessage(retry.error) ??
    errorMessage(withdraw.error) ??
    errorMessage(restore.error);
  return (
    <div className="flex flex-col gap-3 rounded bg-white p-3">
      <h3 className="font-semibold">Review</h3>
      {error ? <p className="text-red-700">{error}</p> : null}
      {source.status === "proposed" ? (
        <div className="flex flex-col gap-2">
          {source.possible_replacements.length ? (
            <ReplacementChoice
              candidates={source.possible_replacements}
              value={choice}
              onChange={setChoice}
            />
          ) : null}
          <label className="flex flex-col">
            Note (required to reject)
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="border p-1"
            />
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => approve.mutate()}
              disabled={approve.isPending || (source.possible_replacements.length > 0 && !choice)}
              className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => reject.mutate()}
              disabled={reject.isPending || !note.trim()}
              className="rounded border px-3 py-1 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}
      {source.status === "failed" ? (
        <button
          type="button"
          onClick={() => retry.mutate()}
          className="w-fit rounded border px-3 py-1"
        >
          Retry ingestion
        </button>
      ) : null}
      {source.status === "ingested" || source.status === "failed" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col">
            Withdrawal reason
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="border px-1"
            />
          </label>
          <button
            type="button"
            onClick={() => withdraw.mutate()}
            disabled={withdraw.isPending || !reason.trim()}
            className="rounded border border-red-700 px-3 py-1 text-red-700 disabled:opacity-50"
          >
            Withdraw everywhere
          </button>
        </div>
      ) : null}
      {source.status === "withdrawn" && source.site_id ? (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => restore.mutate()}
            disabled={restore.isPending || restore.isSuccess}
            className="w-fit rounded border px-3 py-1 disabled:opacity-50"
          >
            Restore page
          </button>
          <span className="text-slate-600">
            {restore.isSuccess
              ? "Restored: the next crawl of the site takes it again."
              : "The next crawl of its site takes the page again as a new version."}
          </span>
        </div>
      ) : null}
      {source.status !== "withdrawn" ? <TakedownForm id={source.id} /> : null}
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
      <legend className="text-amber-900">
        Possible replacement: this file is at the canonical link of an ingested source.
      </legend>
      {candidates.map((c) => (
        <label key={c.id}>
          <input
            type="radio"
            name="replacement"
            value={c.id}
            checked={value === c.id}
            onChange={() => onChange(c.id)}
          />{" "}
          Replace {c.title} ({c.publisher})
        </label>
      ))}
      <label>
        <input
          type="radio"
          name="replacement"
          value="keep"
          checked={value === "keep"}
          onChange={() => onChange("keep")}
        />{" "}
        Keep both
      </label>
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
      <span className="w-full font-semibold">Record a takedown request</span>
      <label className="flex flex-col">
        Reference
        <input
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          required
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Requested on
        <input
          type="date"
          value={requestedOn}
          onChange={(e) => setRequestedOn(e.target.value)}
          required
          className="border px-1"
        />
      </label>
      <label>
        <input type="checkbox" checked={breach} onChange={(e) => setBreach(e.target.checked)} />{" "}
        Licence breach we found (due today)
      </label>
      <label>
        <input
          type="checkbox"
          checked={grounds || breach}
          disabled={breach}
          onChange={(e) => setGrounds(e.target.checked)}
        />{" "}
        On licence grounds
      </label>
      <button type="submit" disabled={record.isPending} className="rounded border px-3 py-1">
        Record
      </button>
      {errorMessage(record.error) ? (
        <p className="w-full text-red-700">{errorMessage(record.error)}</p>
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
    <div className="flex flex-wrap items-end gap-2 rounded bg-white p-3">
      <label className="flex flex-col">
        Licence or permission letter (PDF, DOCX, TXT, EML, image)
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <button
        type="button"
        onClick={() => upload.mutate()}
        disabled={!file || upload.isPending}
        className="rounded border px-3 py-1 disabled:opacity-50"
      >
        Attach
      </button>
      {errorMessage(upload.error) ? (
        <p className="text-red-700">{errorMessage(upload.error)}</p>
      ) : null}
    </div>
  );
}
