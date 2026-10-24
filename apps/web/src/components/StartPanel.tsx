import type { ModelOption, Workspace } from "../api/types";
import {
  EXTERNAL_NOTE,
  modelLabel,
  panelView,
  selectModel,
  selectWorkspace,
  type StartChoice,
} from "../lib/startPanel";

interface Props {
  workspaces: Workspace[];
  models: ModelOption[];
  choice: StartChoice;
  onChange: (choice: StartChoice) => void;
}

// P1a-12: workspace (hidden when the tenant has one), model (hidden when one is enabled)
// and reasoning, pre-filled from the workspace's defaults. Fixed once the conversation
// starts; the conversation header shows them read-only.
export function StartPanel({ workspaces, models, choice, onChange }: Props) {
  const view = panelView(choice, workspaces, models);
  return (
    <fieldset className="flex flex-col gap-3 rounded-control border bg-surface p-3 text-ui">
      <legend className="px-1 font-strong">New conversation</legend>
      {view.showWorkspace ? (
        <label className="flex flex-col gap-1">
          Workspace
          <select
            value={choice.workspaceId ?? ""}
            onChange={(e) => onChange(selectWorkspace(e.target.value, workspaces, models))}
            className="rounded-control border px-2 py-1"
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
      ) : view.workspace ? (
        <p>Workspace: {view.workspace.name}</p>
      ) : null}
      {view.showModel ? (
        <label className="flex flex-col gap-1">
          Model
          <select
            value={choice.model ?? ""}
            onChange={(e) => onChange(selectModel(choice, e.target.value, models))}
            className="rounded-control border px-2 py-1"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {modelLabel(m)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {view.external ? (
        <p
          data-testid="external-note"
          className="rounded-control bg-warning-subtle px-2 py-1 text-warning"
        >
          {EXTERNAL_NOTE}
        </p>
      ) : null}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={choice.reasoning}
          disabled={!view.reasoningAvailable}
          onChange={(e) => onChange({ ...choice, reasoning: e.target.checked })}
        />
        Reasoning
        {view.reasoningAvailable ? null : (
          <span className="text-fg-muted">(not available for this model)</span>
        )}
      </label>
      <p className="text-fg-muted">
        These settings cannot be changed once the conversation has started.
      </p>
    </fieldset>
  );
}
