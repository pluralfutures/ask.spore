import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";

import { ApiError, contentApi } from "../../api/client";
import { Propose } from "./Propose";
import { Register } from "./Register";
import { SiteDetail } from "./SiteDetail";
import { Sites } from "./Sites";
import { SourceDetail } from "./SourceDetail";
import { Tags } from "./Tags";
import { Takedowns } from "./Takedowns";
import { Loading } from "../../ui/States";

// Content operations console (P1b-05, architecture §7.3): the source register with its
// approval flow, takedowns, sites and tags. For internal users with a content role; the
// API answers 403 to anyone else, and this page then says so. Metadata only: the console
// never shows document text beyond titles; chunks are spot-checked in the private RAGFlow
// UI (a loopback link, opened over an SSH tunnel by an operator).
export function ContentConsole() {
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
  const link = ({ isActive }: { isActive: boolean }) =>
    isActive ? "font-strong underline" : "underline";
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 text-ui">
      <header className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-title font-strong">Content console</h1>
        <nav className="flex gap-3">
          <NavLink end to="/content" className={link}>
            Register
          </NavLink>
          <NavLink to="/content/propose" className={link}>
            Propose
          </NavLink>
          <NavLink to="/content/takedowns" className={link}>
            Takedowns
          </NavLink>
          <NavLink to="/content/sites" className={link}>
            Sites
          </NavLink>
          <NavLink to="/content/tags" className={link}>
            Tags
          </NavLink>
        </nav>
        <span className="text-fg-muted">Your roles: {roles.join(", ")}</span>
      </header>
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
