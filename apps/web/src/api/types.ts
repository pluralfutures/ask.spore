// Aliases over the types generated from apps/api/openapi.json (`pnpm gen:api`).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ConversationSummary = Schemas["ConversationSummary"];
export type ConversationCreated = Schemas["ConversationCreated"];
export type ConversationCreateIn = Schemas["ConversationCreateIn"];
export type Workspace = Schemas["WorkspaceOut"];
export type ModelOption = Schemas["ModelOptionOut"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type Message = Schemas["MessageOut"];
export type Citation = Schemas["CitationOut"];
export type FeedbackIn = Schemas["FeedbackIn"];
export type FeedbackOut = Schemas["FeedbackOut"];
export type TokenData = Schemas["TokenData"];
export type CitationsData = Schemas["CitationsData"];
export type DoneData = Schemas["DoneData"];
export type ErrorData = Schemas["ErrorData"];
export type AuthMode = Schemas["AuthModeOut"]["mode"];
export type Me = Schemas["MeOut"];
export type TenantOut = Schemas["TenantOut"];
export type EntitlementsIn = Schemas["EntitlementsIn"];
export type EntitlementsOut = Schemas["EntitlementsOut"];
export type NoticeOut = Schemas["NoticeOut"];
export type OperatorOptions = Schemas["OperatorOptionsOut"];
export type TenantCreateIn = Schemas["TenantCreateIn"];
export type AdminInviteIn = Schemas["AdminInviteIn"];
export type OperatorWorkspace = Schemas["OperatorWorkspaceOut"];
export type WorkspaceCreateIn = Schemas["WorkspaceCreateIn"];

export type ChatStreamEvent =
  | { event: "token"; data: TokenData }
  | { event: "citations"; data: CitationsData }
  | { event: "done"; data: DoneData }
  | { event: "error"; data: ErrorData };
