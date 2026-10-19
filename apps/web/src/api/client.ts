// Typed client for /api/v1. The browser never talks to RAGFlow or the LLM.
import { readEvents } from "../lib/sse";
import type {
  AuthMode,
  ChatStreamEvent,
  ConversationCreated,
  ConversationDetail,
  ConversationSummary,
  FeedbackIn,
  FeedbackOut,
  Me,
} from "./types";

const BASE = "/api/v1";

// Two sign-in modes, chosen by the API ([auth] mode, GET /auth/mode):
// - "oidc" (P1a-02): emailed sign-in links. The session is an HttpOnly cookie set by the
//   API; this code never sees a token.
// - "phase0" (P0-06, kept for the eval harness): the shared bearer token and the user's
//   email, entered once per browser session and kept in sessionStorage, never in the
//   bundle.
export interface Credentials {
  token: string;
  email: string;
}

const CREDENTIALS_KEY = "askspore.phase0.credentials";

export function loadCredentials(): Credentials | null {
  try {
    const raw = sessionStorage.getItem(CREDENTIALS_KEY);
    return raw ? (JSON.parse(raw) as Credentials) : null;
  } catch {
    return null;
  }
}

export function saveCredentials(credentials: Credentials): void {
  try {
    sessionStorage.setItem(CREDENTIALS_KEY, JSON.stringify(credentials));
  } catch {
    // Storage unavailable: the user signs in again on reload.
  }
}

export function clearCredentials(): void {
  try {
    sessionStorage.removeItem(CREDENTIALS_KEY);
  } catch {
    // ignore
  }
}

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`API request failed with status ${status}`);
  }
}

let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal) {
  const credentials = loadCredentials();
  const headers: Record<string, string> = {};
  if (credentials) {
    headers.Authorization = `Bearer ${credentials.token}`;
    headers["X-User-Email"] = credentials.email;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    credentials: "same-origin",
  });
  if (response.status === 401) {
    clearCredentials();
    onUnauthorized();
  }
  if (!response.ok) throw new ApiError(response.status);
  return response;
}

async function json<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await (await send(method, path, body)).json()) as T;
}

export async function authMode(): Promise<AuthMode> {
  const response = await fetch(`${BASE}/auth/mode`, { credentials: "same-origin" });
  if (!response.ok) return "phase0";
  return ((await response.json()) as { mode: AuthMode }).mode;
}

// The emailed link's landing page (P1a-02) calls this, and only from its button.
export async function completeSignIn(
  token: string,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  const response = await fetchImpl(`${BASE}/auth/link/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    credentials: "same-origin",
  });
  return response.ok;
}

export async function requestSignInLink(email: string): Promise<void> {
  const response = await fetch(`${BASE}/auth/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status);
}

export async function signOut(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: "POST", credentials: "same-origin" });
}

export async function currentUser(): Promise<Me | null> {
  const response = await fetch(`${BASE}/me`, { credentials: "same-origin" });
  if (response.status === 401) return null;
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as Me;
}

export const api = {
  listConversations: () => json<ConversationSummary[]>("GET", "/conversations"),
  createConversation: () => json<ConversationCreated>("POST", "/conversations"),
  getConversation: (id: string) => json<ConversationDetail>("GET", `/conversations/${id}`),
  deleteConversation: async (id: string) => {
    await send("DELETE", `/conversations/${id}`);
  },
  sendFeedback: (messageId: string, feedback: FeedbackIn) =>
    json<FeedbackOut>("POST", `/messages/${messageId}/feedback`, feedback),
  async *ask(id: string, question: string, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    const response = await send("POST", `/conversations/${id}/messages`, { question }, signal);
    yield* readEvents(response);
  },
};
