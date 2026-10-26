import type { Me } from "../api/types";

// P1b-10: the operator and content consoles are internal staff pages, not gated; every
// other page (conversations, files, tenant admin) waits for the notice to be accepted.
const UNGATED_PREFIXES = ["/operator", "/content"];

export function gateApplies(path: string): boolean {
  return !UNGATED_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function mustAccept(me: Me | null | undefined, path: string): boolean {
  return gateApplies(path) && me?.consent_required === true;
}
