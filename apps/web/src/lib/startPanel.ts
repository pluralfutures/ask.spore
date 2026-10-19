import type { ConversationCreateIn, ModelOption, Workspace } from "../api/types";

// The conversation start panel (P1a-12): workspace, model and reasoning, chosen once and
// fixed for the conversation. Pure logic, so the panel's states are tested without a DOM.

export interface StartChoice {
  workspaceId: string | null;
  model: string | null;
  reasoning: boolean;
}

export interface PanelView {
  // A tenant with one workspace, or one enabled model, sees no chooser for it.
  showWorkspace: boolean;
  showModel: boolean;
  workspace: Workspace | null;
  model: ModelOption | null;
  // The selected model has a reasoning switch; otherwise the toggle is off and disabled.
  reasoningAvailable: boolean;
  // The selected model is served outside the EU (compliance addendum, Oct 18-19, 2026).
  external: boolean;
}

export const EXTERNAL_LABEL = "served outside the EU";
export const EXTERNAL_NOTE = "This model is served outside the EU.";

// The workspace's default model when the user may pick it, else the tenant-wide default
// the API marks, else the first listed. Reasoning follows the workspace's default where
// the model has a switch.
export function defaultsFor(workspace: Workspace | null, models: ModelOption[]): StartChoice {
  const model =
    models.find((m) => m.id === workspace?.default_model) ??
    models.find((m) => m.default) ??
    models[0] ??
    null;
  return {
    workspaceId: workspace?.id ?? null,
    model: model?.id ?? null,
    reasoning: Boolean(workspace?.default_reasoning && model?.reasoning_switch),
  };
}

export function initialChoice(workspaces: Workspace[], models: ModelOption[]): StartChoice {
  return defaultsFor(workspaces[0] ?? null, models);
}

// Picking another workspace re-applies its defaults; picking a model keeps the reasoning
// setting where the new model has a switch.
export function selectWorkspace(
  workspaceId: string,
  workspaces: Workspace[],
  models: ModelOption[],
): StartChoice {
  return defaultsFor(workspaces.find((w) => w.id === workspaceId) ?? null, models);
}

export function selectModel(choice: StartChoice, modelId: string, models: ModelOption[]) {
  const model = models.find((m) => m.id === modelId);
  return { ...choice, model: modelId, reasoning: choice.reasoning && !!model?.reasoning_switch };
}

export function panelView(
  choice: StartChoice,
  workspaces: Workspace[],
  models: ModelOption[],
): PanelView {
  const model = models.find((m) => m.id === choice.model) ?? null;
  return {
    showWorkspace: workspaces.length > 1,
    showModel: models.length > 1,
    workspace: workspaces.find((w) => w.id === choice.workspaceId) ?? null,
    model,
    reasoningAvailable: !!model?.reasoning_switch,
    external: !!model?.external,
  };
}

export function modelLabel(model: ModelOption): string {
  return model.external ? `${model.display_name} (${EXTERNAL_LABEL})` : model.display_name;
}

// The create request: only the user's own choice. Dataset and document IDs never leave
// the server; the workspace's corpus is resolved there.
export function createBody(choice: StartChoice): ConversationCreateIn {
  const body: ConversationCreateIn = { reasoning: choice.reasoning };
  if (choice.workspaceId) body.workspace_id = choice.workspaceId;
  if (choice.model) body.model = choice.model;
  return body;
}

const REFUSALS: Record<string, string> = {
  workspace_required: "Choose a workspace.",
  no_workspace: "No workspace has been set up for your organisation yet.",
  model_not_enabled: "That model is not available to your organisation.",
  model_unavailable: "That model is not available right now.",
  external_not_entitled: "That model is not available to your organisation.",
  reasoning_unsupported: "That model cannot reason; switch reasoning off.",
  mode_not_enabled: "That answer mode is not available to your organisation.",
};

export function refusalText(code: string | null): string {
  return (code && REFUSALS[code]) || "The conversation could not be started.";
}
