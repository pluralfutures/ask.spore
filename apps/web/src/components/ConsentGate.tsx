import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import { useLocation } from "react-router-dom";

import { api, setConsentRequiredHandler } from "../api/client";
import type { ConsentNotice } from "../api/types";
import { mustAccept } from "../lib/consent";
import { Button } from "../ui/Button";
import { Checkbox } from "../ui/Checkbox";
import { Notice } from "../ui/Notice";
import { PageError, Skeleton } from "../ui/States";
import { cardClass } from "../ui/cardClass";
import { GFM_PLUGINS, TABLE_COMPONENTS } from "./markdownTable";

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
  if (notice.isPending)
    return (
      <div className="mx-auto w-full max-w-3xl p-4 md:px-8 md:py-6">
        <Skeleton />
      </div>
    );
  if (!notice.data) return <PageError>The notice could not be loaded.</PageError>;
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
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 pb-0 text-ui md:px-8 md:py-6">
      <h1 className="text-display font-strong">{notice.title}</h1>
      {changed ? (
        <p className="text-warning">
          The notice has changed since you last accepted it. Please read and accept the new version
          to continue.
        </p>
      ) : (
        <p>Please read and accept the notice before your first conversation.</p>
      )}
      <section aria-labelledby="consent-summary" className={cardClass("flex flex-col gap-3")}>
        <h2 id="consent-summary" className="text-heading font-strong">
          In short
        </h2>
        <NoticeMarkdown text={notice.summary} />
      </section>
      {/* UX-12: the full notice scrolls in its own box from 768 px, with a tab stop so the
          keyboard can scroll it; on phone the page scrolls and the accept row stays in view. */}
      <section
        aria-labelledby="consent-full"
        tabIndex={0}
        data-testid="consent-full"
        className={cardClass("flex flex-col gap-3 md:max-h-[50vh] md:overflow-y-auto")}
      >
        <h2 id="consent-full" className="text-heading font-strong">
          Full notice
        </h2>
        <NoticeMarkdown text={notice.text} />
      </section>
      <div
        data-testid="consent-accept"
        className="flex flex-col gap-3 border-t bg-canvas py-3 max-md:sticky max-md:bottom-0 md:border-t-0 md:py-0"
      >
        <Checkbox checked={read} onChange={(e) => setRead(e.target.checked)}>
          I have read the notice ({notice.version}) and accept it.
        </Checkbox>
        <Button variant="primary" className="w-fit" disabled={!read || pending} onClick={onAccept}>
          Accept and continue
        </Button>
        {failed ? (
          <Notice tone="danger">The acceptance was not recorded. Reload and try again.</Notice>
        ) : null}
      </div>
    </div>
  );
}

// UX-12: the notice's Markdown keeps its structure. Its headings sit under the page's
// "Full notice" (h2), so the file's #, ## and ### all render as h3 and deeper levels keep
// theirs; lists get their markers back (preflight strips them). No raw HTML is rendered.
const heading = (level: 3 | 4 | 5 | 6) => {
  const Tag = `h${level}` as const;
  const Heading: Components["h1"] = ({ children }) => (
    <Tag className={level === 3 ? "text-heading font-strong" : "font-strong"}>{children}</Tag>
  );
  return Heading;
};

const NOTICE_COMPONENTS: Components = {
  ...TABLE_COMPONENTS,
  h1: heading(3),
  h2: heading(3),
  h3: heading(3),
  h4: heading(4),
  h5: heading(5),
  h6: heading(6),
};

function NoticeMarkdown({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2 [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&>h3]:mt-2 [&>h4]:mt-1">
      <Markdown remarkPlugins={GFM_PLUGINS} components={NOTICE_COMPONENTS}>
        {text}
      </Markdown>
    </div>
  );
}
