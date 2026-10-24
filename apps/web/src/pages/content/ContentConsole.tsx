import { useQuery } from "@tanstack/react-query";
import { Route, Routes, useLocation } from "react-router-dom";

import { ApiError, contentApi } from "../../api/client";
import { Propose } from "./Propose";
import { Register } from "./Register";
import { SiteDetail } from "./SiteDetail";
import { Sites } from "./Sites";
import { SourceDetail } from "./SourceDetail";
import { Tags } from "./Tags";
import { Takedowns } from "./Takedowns";
import { Loading } from "../../ui/States";
import { Tabs } from "../../ui/Tabs";

// Content operations console (P1b-05, architecture §7.3): the source register with its
// approval flow, takedowns, sites and tags. For internal users with a content role; the
// API answers 403 to anyone else, and this page then says so. Metadata only: the console
// never shows document text beyond titles; chunks are spot-checked in the private RAGFlow
// UI (a loopback link, opened over an SSH tunnel by an operator).
const SECTIONS = [
  ["Register", "/content"],
  ["Propose", "/content/propose"],
  ["Takedowns", "/content/takedowns"],
  ["Sites", "/content/sites"],
  ["Tags", "/content/tags"],
] as const;

export function ContentConsole() {
  const { pathname } = useLocation();
  const me = useQuery({ queryKey: ["content", "me"], queryFn: contentApi.me });
  if (me.error instanceof ApiError && me.error.status === 403) {
    return <main className="mx-auto max-w-3xl p-4 text-ui">Content roles only.</main>;
  }
  if (!me.data)
    return (
      <main className="mx-auto max-w-3xl p-4 text-ui">
        <Loading />
      </main>
    );
  const roles = me.data.roles;
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 text-ui">
      <header className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-title font-strong">Content console</h1>
        <span className="text-fg-muted">Your roles: {roles.join(", ")}</span>
      </header>
      <Tabs
        label="Content console"
        tabs={SECTIONS.map(([label, to]) => ({
          label,
          to,
          current: to === "/content" ? pathname === to : pathname.startsWith(to),
        }))}
      />
      <Routes>
        <Route index element={<Register />} />
        <Route path="propose" element={<Propose roles={roles} />} />
        <Route path="sources/:id" element={<SourceDetail roles={roles} />} />
        <Route path="takedowns" element={<Takedowns />} />
        <Route path="sites" element={<Sites roles={roles} />} />
        <Route path="sites/:id" element={<SiteDetail roles={roles} />} />
        <Route path="tags" element={<Tags roles={roles} />} />
      </Routes>
    </main>
  );
}
