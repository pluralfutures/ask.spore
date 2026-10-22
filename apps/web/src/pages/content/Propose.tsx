import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { contentApi } from "../../api/client";
import type { ProposeOut } from "../../api/types";
import {
  LICENCE_BASES,
  canEdit,
  emptyProposal,
  errorMessage,
  proposalForm,
  type ProposalFields,
} from "../../lib/content";

// The propose form (P1b-05): a file upload or a URL, with the manifest's metadata and
// tags. The licence basis is always required; a licence or permission letter is optional,
// downloadable or not (decision 10). Nothing reaches RAGFlow before a reviewer approves.
export function Propose({ roles }: { roles: string[] }) {
  const tags = useQuery({ queryKey: ["content", "tags"], queryFn: contentApi.tags });
  const [fields, setFields] = useState<ProposalFields>(emptyProposal);
  const [file, setFile] = useState<File | null>(null);
  const [licence, setLicence] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const propose = useMutation({ mutationFn: contentApi.propose });

  if (!canEdit(roles)) return <p>Proposing needs the content editor role.</p>;

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = proposalForm(fields, file, licence);
    if ("error" in result) {
      setProblem(result.error);
      return;
    }
    setProblem(null);
    propose.mutate(result.form);
  }

  const set = (key: keyof ProposalFields) => (value: string | boolean | string[]) =>
    setFields({ ...fields, [key]: value });
  return (
    <form onSubmit={submit} className="flex max-w-2xl flex-col gap-2 rounded bg-white p-3">
      <h2 className="font-semibold">Propose a source</h2>
      <label className="flex flex-col">
        File (PDF, DOCX, PPTX, HTML, Markdown)
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="flex flex-col">
        or URL
        <input
          value={fields.url}
          onChange={(e) => set("url")(e.target.value)}
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Title
        <input
          value={fields.title}
          onChange={(e) => set("title")(e.target.value)}
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Publisher
        <input
          value={fields.publisher}
          onChange={(e) => set("publisher")(e.target.value)}
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Publication date
        <input
          type="date"
          value={fields.publishedOn}
          onChange={(e) => set("publishedOn")(e.target.value)}
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Canonical link (the publisher's page; the URL itself for a URL)
        <input
          value={fields.canonicalUrl}
          onChange={(e) => set("canonicalUrl")(e.target.value)}
          className="border px-1"
        />
      </label>
      <label className="flex flex-col">
        Licence basis
        <input
          list="licence-bases"
          value={fields.licenceBasis}
          onChange={(e) => set("licenceBasis")(e.target.value)}
          className="border px-1"
        />
        <datalist id="licence-bases">
          {LICENCE_BASES.map((basis) => (
            <option key={basis} value={basis} />
          ))}
        </datalist>
      </label>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Tags</legend>
        {tags.data?.map((t) => (
          <label key={t.tag}>
            <input
              type="checkbox"
              checked={fields.tags.includes(t.tag)}
              onChange={(e) =>
                set("tags")(
                  e.target.checked
                    ? [...fields.tags, t.tag]
                    : fields.tags.filter((x) => x !== t.tag),
                )
              }
            />{" "}
            {t.tag}
          </label>
        ))}
      </fieldset>
      <label>
        <input
          type="checkbox"
          checked={fields.downloadable}
          onChange={(e) => set("downloadable")(e.target.checked)}
        />{" "}
        Users may download the file (only where the licence permits redistribution)
      </label>
      <label className="flex flex-col">
        Licence or permission letter (optional)
        <input type="file" onChange={(e) => setLicence(e.target.files?.[0] ?? null)} />
      </label>
      <button
        type="submit"
        disabled={propose.isPending}
        className="w-fit rounded bg-slate-900 px-3 py-1 text-white"
      >
        Propose
      </button>
      {problem ? <p className="text-red-700">{problem}</p> : null}
      {errorMessage(propose.error) ? (
        <p className="text-red-700">{errorMessage(propose.error)}</p>
      ) : null}
      {propose.data ? <ProposeResult result={propose.data} /> : null}
    </form>
  );
}

const OUTCOMES: Record<ProposeOut["outcome"], string> = {
  proposed: "Proposed: it waits for a reviewer.",
  pending: "This file is already in the register, waiting for a reviewer.",
  duplicate: "This file is already ingested in every tag you chose.",
  retag: "This file is already ingested; adding tags needs a reviewer.",
  taken_down: "This file was withdrawn after a takedown request and is not proposed again.",
};

export function ProposeResult({ result }: { result: ProposeOut }) {
  return (
    <div data-testid="propose-result" className="rounded bg-slate-50 p-2">
      <p>
        {OUTCOMES[result.outcome]}{" "}
        <Link to={`/content/sources/${result.source_id}`} className="underline">
          Open the source
        </Link>
      </p>
      {result.possible_replacements.length ? (
        <p className="text-amber-900">
          Possible replacement of{" "}
          {result.possible_replacements.map((r) => `${r.title} (${r.publisher})`).join("; ")}: the
          reviewer chooses replace or keep both.
        </p>
      ) : null}
    </div>
  );
}
