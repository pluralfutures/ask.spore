import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { contentApi } from "../../api/client";
import type { ContentSiteDetail, SiteUpload, UploadReport } from "../../api/types";
import {
  MEMBER_NOTES,
  MEMBER_OUTCOMES,
  canReview,
  declarationText,
  emptyUpload,
  errorMessage,
  hostOf,
  uploadForm,
  type UploadFields,
} from "../../lib/content";
import { formatDate } from "../../lib/format";
import { StatusBadge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { Checkbox, Radio } from "../../ui/Checkbox";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { Notice } from "../../ui/Notice";
import { cardClass } from "../../ui/cardClass";
import { Table, Td, Th } from "../../ui/Table";

// Uploaded crawls (P2SR01-05): an editor uploads a ZIP of Markdown pages made outside the
// platform, with the crawl date, full or partial, and the declaration; the inspection
// report is shown once, here, and kept in this component's state only (the server keeps
// counts and codes, never the file names). A reviewer releases or rejects each upload.

/** The editor's form. Without ``site`` it registers a new upload site too. */
export function UploadCrawl({ site }: { site?: ContentSiteDetail }) {
  const queryClient = useQueryClient();
  const tags = useQuery({
    queryKey: ["content", "tags"],
    queryFn: contentApi.tags,
    enabled: site === undefined,
  });
  const [fields, setFields] = useState<UploadFields>(emptyUpload);
  const [file, setFile] = useState<File | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (form: FormData) => contentApi.uploadCrawl(form, site?.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content"] }),
  });
  const host = site ? site.host : hostOf(fields.startUrl);
  function submit(event: FormEvent) {
    event.preventDefault();
    const built = uploadForm(fields, file, site === undefined);
    if ("error" in built) {
      setInvalid(built.error);
      return;
    }
    setInvalid(null);
    upload.mutate(built.form);
  }
  const text = (key: "startUrl" | "name" | "publisher" | "licenceBasis", label: string) => (
    <Field label={label}>
      <Input
        value={fields[key]}
        onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
        required
      />
    </Field>
  );
  return (
    <form
      onSubmit={submit}
      className={cardClass("flex max-w-2xl flex-col gap-4")}
      data-testid="upload-crawl"
    >
      <h2 className="text-heading font-strong">Upload crawl</h2>
      <p className="text-fg-muted">
        One ZIP of Markdown pages from one crawl of {site ? site.host : "one site"}: each file
        starts with its page URL (a Source comment or a url key). A reviewer releases it.
      </p>
      {site === undefined ? (
        <>
          {text("startUrl", "Start URL")}
          {text("name", "Name")}
          {text("publisher", "Publisher")}
          {text("licenceBasis", "Licence basis")}
          <fieldset className="flex flex-wrap gap-x-4 gap-y-2">
            <legend className="mb-2 text-ui font-strong">Tags</legend>
            {tags.data?.map((t) => (
              <Checkbox
                key={t.tag}
                checked={fields.tags.includes(t.tag)}
                onChange={(e) =>
                  setFields({
                    ...fields,
                    tags: e.target.checked
                      ? [...fields.tags, t.tag]
                      : fields.tags.filter((x) => x !== t.tag),
                  })
                }
              >
                {t.tag}
              </Checkbox>
            ))}
          </fieldset>
        </>
      ) : null}
      <Field label="ZIP of the crawl (up to 200 MB, 2,000 pages)">
        <Input
          type="file"
          accept=".zip,application/zip"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </Field>
      <Field label="Crawl date">
        <Input
          type="date"
          value={fields.crawledOn}
          onChange={(e) => setFields({ ...fields, crawledOn: e.target.value })}
          required
        />
      </Field>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-ui font-strong">This crawl is</legend>
        <Radio
          name="mode"
          checked={fields.mode === "partial"}
          onChange={() => setFields({ ...fields, mode: "partial" })}
        >
          Partial: pages missing from the ZIP stay as they are
        </Radio>
        <Radio
          name="mode"
          checked={fields.mode === "full"}
          onChange={() => setFields({ ...fields, mode: "full" })}
        >
          Full: pages missing from the ZIP are withdrawn
        </Radio>
      </fieldset>
      <Checkbox
        checked={fields.declared}
        onChange={(e) => setFields({ ...fields, declared: e.target.checked })}
        data-testid="upload-declaration"
      >
        {declarationText(host, fields.crawledOn)}
      </Checkbox>
      <Button variant="primary" className="w-fit" type="submit" disabled={upload.isPending}>
        Upload
      </Button>
      {invalid ? <Notice tone="danger">{invalid}</Notice> : null}
      {errorMessage(upload.error) ? (
        <Notice tone="danger">{errorMessage(upload.error)}</Notice>
      ) : null}
      {upload.data ? (
        <>
          <Notice tone="success" role="status">
            Uploaded: it waits for a reviewer to release it.
          </Notice>
          <UploadReportView report={upload.data} />
        </>
      ) : null}
    </form>
  );
}

/** The inspection report: counts, the full upload's withdrawals, and every member. */
export function UploadReportView({ report }: { report: UploadReport }) {
  return (
    <div className="flex flex-col gap-2" data-testid="upload-report">
      <p>
        {report.accepted} accepted · {report.refused} refused · {report.skipped} skipped · crawl of{" "}
        {formatDate(report.crawled_on)} · {report.mode}
      </p>
      {report.would_withdraw !== null ? (
        <Notice tone="warning" data-testid="upload-would-withdraw">
          A full upload: {report.would_withdraw} live page
          {report.would_withdraw === 1 ? "" : "s"} missing from this ZIP will be withdrawn.
        </Notice>
      ) : null}
      <Table>
        <thead>
          <tr>
            <Th>File</Th>
            <Th>Outcome</Th>
            <Th>Page</Th>
            <Th>Title</Th>
          </tr>
        </thead>
        <tbody>
          {report.members.map((member) => (
            <tr key={member.index}>
              <Td label="File" className="break-all">
                {member.name}
              </Td>
              <Td label="Outcome">
                {MEMBER_OUTCOMES[member.outcome] ?? member.outcome}
                {member.note ? (
                  <span className="text-warning">
                    {" "}
                    · {MEMBER_NOTES[member.note] ?? member.note}
                    {member.special_category
                      ? `: ${member.special_category.replace(/_/g, " ")}`
                      : ""}
                  </span>
                ) : null}
              </Td>
              <Td label="Page" className="break-all">
                {member.url ?? "—"}
              </Td>
              <Td label="Title">{member.title ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

/** An upload site's uploads, newest first, with the reviewer's release and reject. */
export function SiteUploads({ site, roles }: { site: ContentSiteDetail; roles: string[] }) {
  if (site.uploads.length === 0) return null;
  return (
    <Card title="Uploads" level={3}>
      <Table>
        <thead>
          <tr>
            <Th>Uploaded</Th>
            <Th>Crawl date</Th>
            <Th>Mode</Th>
            <Th>Status</Th>
            <Th numeric>Accepted</Th>
            <Th>Imported</Th>
            <Th>Released by</Th>
          </tr>
        </thead>
        <tbody>
          {site.uploads.map((upload) => (
            <tr key={upload.id}>
              <Td label="Uploaded">
                {formatDate(upload.uploaded_at)} · {upload.uploaded_by ?? "CLI"}
              </Td>
              <Td label="Crawl date">{formatDate(upload.crawled_on)}</Td>
              <Td label="Mode">{upload.mode}</Td>
              <Td label="Status">
                <StatusBadge kind="upload" status={upload.status} />
                {upload.error ? ` ${upload.error}` : ""}
              </Td>
              <Td label="Accepted" numeric>
                {upload.accepted_count} of {upload.member_count}
              </Td>
              <Td label="Imported">{importCounts(upload)}</Td>
              <Td label="Released by">
                {upload.released_by ?? "—"}
                {upload.review_note ? ` · ${upload.review_note}` : ""}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {canReview(roles)
        ? site.uploads
            .filter((u) => u.status === "staged")
            .map((u) => <ReleaseUpload key={u.id} site={site} upload={u} />)
        : null}
    </Card>
  );
}

export function importCounts(upload: SiteUpload): string {
  if (upload.status !== "imported") return "—";
  return (
    `${upload.new_count} new · ${upload.changed_count} changed · ` +
    `${upload.unchanged_count} unchanged · ${upload.blocked_count} blocked · ` +
    `${upload.withdrawn_count} withdrawn`
  );
}

/** A reviewer's release (D7): the report read again from the staged ZIP, then one click;
 * on a proposed site the release approves the site too. */
export function ReleaseUpload({ site, upload }: { site: ContentSiteDetail; upload: SiteUpload }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["content"] });
  const [note, setNote] = useState("");
  const report = useQuery({
    queryKey: ["content", "upload-report", upload.id],
    queryFn: () => contentApi.uploadReport(site.id, upload.id),
  });
  const release = useMutation({
    mutationFn: () => contentApi.releaseUpload(site.id, upload.id, note.trim() || null),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: () => contentApi.rejectUpload(site.id, upload.id, note),
    onSuccess: refresh,
  });
  const withdraws = report.data?.would_withdraw;
  const error =
    errorMessage(report.error) ?? errorMessage(release.error) ?? errorMessage(reject.error);
  return (
    <div className="flex flex-col gap-2" data-testid="release-upload">
      <h4 className="font-strong">Upload of {formatDate(upload.uploaded_at)}</h4>
      {report.data ? <UploadReportView report={report.data} /> : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Note (required to reject)">
          <Input value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Button
          variant="primary"
          onClick={() => release.mutate()}
          disabled={release.isPending || !report.data}
        >
          {site.status === "proposed" ? "Approve site and release" : "Release"}
          {withdraws !== undefined && withdraws !== null ? ` (withdraws ${withdraws})` : ""}
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
  );
}
