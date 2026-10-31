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
export type InvitationResent = Schemas["InvitationResentOut"];
export type TerminatedTenant = Schemas["TerminatedTenantOut"];
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
export type AdminUser = Schemas["AdminUserOut"];
export type UserInviteIn = Schemas["UserInviteIn"];
export type UserChangeIn = Schemas["UserChangeIn"];
export type WorkspaceDefaultsIn = Schemas["WorkspaceDefaultsIn"];
export type WorkspacePrompt = Schemas["WorkspacePromptOut"];
export type TenantSettings = Schemas["TenantSettingsOut"];
// P2A-05: the tenant admin's usage section (counts only).
export type UsageOut = Schemas["UsageOut"];
// P2A-08: time-boxed support access.
export type SupportGrant = Schemas["SupportGrantOut"];
export type SupportGrantIn = Schemas["SupportGrantIn"];
export type OperatorSupportGrant = Schemas["OperatorSupportGrantOut"];
export type SupportConversation = Schemas["SupportConversationOut"];
export type SupportSettings = Schemas["SupportSettingsOut"];
// Login policy and tenant discovery (P1b-06).
export type DiscoverOut = Schemas["DiscoverOut"];
export type LoginPolicyIn = Schemas["LoginPolicyIn"];
export type LoginPolicyOut = Schemas["LoginPolicyOut"];
// Client SSO (P1b-07).
export type SsoSourceIn =
  | Schemas["EntraSourceIn"]
  | Schemas["GoogleSourceIn"]
  | Schemas["OidcSourceIn"]
  | Schemas["SamlSourceIn"];
export type SsoStartOut = Schemas["SsoStartOut"];
// Second factor for tenant admins (P1b-08).
export type MfaRequiredOut = Schemas["MfaRequiredOut"];

export type ChatStreamEvent =
  | { event: "token"; data: TokenData }
  | { event: "citations"; data: CitationsData }
  | { event: "done"; data: DoneData }
  | { event: "error"; data: ErrorData };
export type WorkspaceFiles = Schemas["WorkspaceFilesOut"];
export type WorkspaceFile = Schemas["WorkspaceFileOut"];
export type WorkspaceSite = Schemas["WorkspaceSiteOut"];
export type DownloadLink = Schemas["DownloadLinkOut"];
export type OperatorSource = Schemas["OperatorSourceOut"];
// Content console (P1b-05).
export type ContentMe = Schemas["ContentMeOut"];
export type ContentSource = Schemas["ContentSourceOut"];
export type ContentSourceDetail = Schemas["ContentSourceDetail"];
export type PauseOut = Schemas["PauseOut"];
export type SourceRef = Schemas["SourceRef"];
export type DocumentLink = Schemas["DocumentLink"];
export type HistoryEntry = Schemas["HistoryEntry"];
export type ContentJob = Schemas["JobOut"];
export type ProposeOut = Schemas["ProposeOut"];
export type ApproveIn = Schemas["ApproveIn"];
export type TakedownIn = Schemas["TakedownIn"];
export type Takedown = Schemas["TakedownOut"];
export type ContentSite = Schemas["SiteOut"];
export type ContentSiteDetail = Schemas["SiteDetail"];
export type SitePage = Schemas["SitePageOut"];
export type SiteCreateIn = Schemas["SiteCreateIn"];
export type SiteSettingsIn = Schemas["SiteSettingsIn"];
// P2SR01: uploaded crawls.
export type UploadReport = Schemas["UploadReportOut"];
export type UploadMember = Schemas["UploadMemberOut"];
export type SiteUpload = Schemas["SiteUploadOut"];
export type ContentTag = Schemas["TagOut"];
export type TagSync = Schemas["TagSyncOut"];
// Operator console, one tenant per page (P1b-12).
export type OperatorTag = Schemas["OperatorTagOut"];
export type TenantSpend = Schemas["TenantSpendOut"];
export type Aggregates = Schemas["AggregatesOut"];
// P1b-10: the use and privacy notice and its acceptance.
export type ConsentNotice = Schemas["ConsentNoticeOut"];
