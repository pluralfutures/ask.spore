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
import { Button } from "../../ui/Button";
import { LINK } from "../../ui/link";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { Checkbox } from "../../ui/Checkbox";
import { Notice } from "../../ui/Notice";
import { cardClass } from "../../ui/cardClass";

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
    <form onSubmit={submit} className={cardClass("flex max-w-2xl flex-col gap-2")}>
      <h2 className="font-strong">Propose a source</h2>
      <Field label="File (PDF, DOCX, PPTX, HTML, Markdown)">
        <Input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Field label="or URL">
        <Input value={fields.url} onChange={(e) => set("url")(e.target.value)} />
      </Field>
      <Field label="Title">
        <Input value={fields.title} onChange={(e) => set("title")(e.target.value)} />
      </Field>
      <Field label="Publisher">
        <Input value={fields.publisher} onChange={(e) => set("publisher")(e.target.value)} />
      </Field>
      <Field label="Publication date">
        <Input
          type="date"
          value={fields.publishedOn}
          onChange={(e) => set("publishedOn")(e.target.value)}
        />
      </Field>
      <Field label="Canonical link (the publisher's page; the URL itself for a URL)">
        <Input value={fields.canonicalUrl} onChange={(e) => set("canonicalUrl")(e.target.value)} />
      </Field>
      <Field label="Licence basis">
        <Input
          list="licence-bases"
          value={fields.licenceBasis}
          onChange={(e) => set("licenceBasis")(e.target.value)}
        />
      </Field>
      <datalist id="licence-bases">
        {LICENCE_BASES.map((basis) => (
          <option key={basis} value={basis} />
        ))}
      </datalist>
      <fieldset className="flex flex-wrap gap-3">
        <legend>Tags</legend>
        {tags.data?.map((t) => (
          <Checkbox
            key={t.tag}
            checked={fields.tags.includes(t.tag)}
            onChange={(e) =>
              set("tags")(
                e.target.checked ? [...fields.tags, t.tag] : fields.tags.filter((x) => x !== t.tag),
              )
            }
          >
            {t.tag}
          </Checkbox>
        ))}
      </fieldset>
      <Checkbox
        checked={fields.downloadable}
        onChange={(e) => set("downloadable")(e.target.checked)}
      >
        Users may download the file (only where the licence permits redistribution)
      </Checkbox>
      <Field label="Licence or permission letter (optional)">
        <Input type="file" onChange={(e) => setLicence(e.target.files?.[0] ?? null)} />
      </Field>
      <Button variant="primary" className="w-fit" type="submit" disabled={propose.isPending}>
        Propose
      </Button>
      {problem ? <Notice tone="danger">{problem}</Notice> : null}
      {errorMessage(propose.error) ? (
        <Notice tone="danger">{errorMessage(propose.error)}</Notice>
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
    <Notice tone="success" data-testid="propose-result">
      <p>
        {OUTCOMES[result.outcome]}{" "}
        <Link to={`/content/sources/${result.source_id}`} className={LINK}>
          Open the source
        </Link>
      </p>
      {result.replaces ? (
        <p data-testid="propose-replaces">
          Same link and title as {result.replaces.title} ({result.replaces.publisher}): once
          approved and ingested, it replaces that source.
        </p>
      ) : null}
      {result.possible_replacements.length ? (
        <p className="text-warning">
          Possible replacement of{" "}
          {result.possible_replacements.map((r) => `${r.title} (${r.publisher})`).join("; ")}: the
          reviewer chooses replace or keep both.
        </p>
      ) : null}
    </Notice>
  );
}
