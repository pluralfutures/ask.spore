import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import { useLocation } from "react-router-dom";

import { api, setConsentRequiredHandler } from "../api/client";
import type { ConsentNotice } from "../api/types";
import { mustAccept } from "../lib/consent";

// The first-login consent gate (P1b-10): until the active use and privacy notice is
// accepted, the app shows the notice instead of any conversation, file or admin page.
// The API refuses those routes too (403 consent_required); this is the user's view of it.
export function ConsentGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });

  useEffect(() => {
    setConsentRequiredHandler(() => void queryClient.invalidateQueries({ queryKey: ["me"] }));
  }, [queryClient]);

  if (!mustAccept(me.data, pathname)) return <>{children}</>;
  return (
    <ConsentPage
      onAccepted={() => {
        void queryClient.invalidateQueries();
      }}
    />
  );
}

function ConsentPage({ onAccepted }: { onAccepted: () => void }) {
  const notice = useQuery({ queryKey: ["consent"], queryFn: api.consent });
  const accept = useMutation({
    mutationFn: (version: string) => api.acceptConsent(version),
    onSuccess: onAccepted,
  });
  if (notice.isPending) return <main className="mx-auto max-w-3xl p-4">Loading…</main>;
  if (!notice.data) {
    return (
      <main className="mx-auto max-w-3xl p-4 text-danger">The notice could not be loaded.</main>
    );
  }
  return (
    <ConsentView
      notice={notice.data}
      pending={accept.isPending}
      failed={accept.isError}
      onAccept={() => accept.mutate(notice.data.version)}
    />
  );
}

export function ConsentView({
  notice,
  pending = false,
  failed = false,
  onAccept,
}: {
  notice: ConsentNotice;
  pending?: boolean;
  failed?: boolean;
  onAccept: () => void;
}) {
  const [read, setRead] = useState(false);
  const changed = notice.accepted_version !== null && notice.accepted_version !== notice.version;
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-4 text-ui">
      <h1 className="text-title font-strong">{notice.title}</h1>
      {changed ? (
        <p className="text-warning">
          The notice has changed since you last accepted it. Please read and accept the new version
          to continue.
        </p>
      ) : (
        <p>Please read and accept the notice before your first conversation.</p>
      )}
      <section aria-labelledby="consent-summary" className="rounded-control bg-surface p-3">
        <h2 id="consent-summary" className="font-strong">
          In short
        </h2>
        <div className="space-y-2">
          <Markdown>{notice.summary}</Markdown>
        </div>
      </section>
      <section
        aria-labelledby="consent-full"
        className="max-h-[50vh] overflow-y-auto rounded-control bg-surface p-3"
      >
        <h2 id="consent-full" className="font-strong">
          Full notice
        </h2>
        <div className="space-y-2">
          <Markdown>{notice.text}</Markdown>
        </div>
      </section>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />I have
        read the notice ({notice.version}) and accept it.
      </label>
      <button
        type="button"
        disabled={!read || pending}
        onClick={onAccept}
        className="w-fit rounded-control bg-primary px-3 py-1 text-on-primary disabled:opacity-50"
      >
        Accept and continue
      </button>
      {failed ? (
        <p className="text-danger">The acceptance was not recorded. Reload and try again.</p>
      ) : null}
    </main>
  );
}
