import { Lock } from "lucide-react";

import type { ModelOption, Workspace } from "../api/types";
import {
  EXTERNAL_NOTE,
  modelLabel,
  panelView,
  selectModel,
  selectWorkspace,
  type StartChoice,
} from "../lib/startPanel";
import { Field } from "../ui/Field";
import { Select } from "../ui/Input";
import { Switch } from "../ui/Switch";
import { Notice } from "../ui/Notice";

interface Props {
  workspaces: Workspace[];
  models: ModelOption[];
  choice: StartChoice;
  onChange: (choice: StartChoice) => void;
}

// P1a-12: workspace (read-only when the tenant has one), model (read-only when one is
// enabled; shown since UX-14, owner decision of Oct 24, 2026) and reasoning, pre-filled
// from the workspace's defaults. Fixed once the conversation starts; the conversation
// header shows them read-only.
export function StartPanel({ workspaces, models, choice, onChange }: Props) {
  const view = panelView(choice, workspaces, models);
  return (
    <fieldset className="flex flex-col gap-4 rounded-card border bg-surface p-4 text-ui md:p-5">
      <legend className="px-1.5 text-heading font-strong">Settings</legend>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {view.showWorkspace ? (
          <Field label="Workspace">
            <Select
              value={choice.workspaceId ?? ""}
              onChange={(e) => onChange(selectWorkspace(e.target.value, workspaces, models))}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
          </Field>
        ) : view.workspace ? (
          <p>Workspace: {view.workspace.name}</p>
        ) : null}
        {view.showModel ? (
          <Field label="Model">
            <Select
              value={choice.model ?? ""}
              onChange={(e) => onChange(selectModel(choice, e.target.value, models))}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {modelLabel(m)}
                </option>
              ))}
            </Select>
          </Field>
        ) : view.model ? (
          <p data-testid="model-readonly">Model: {modelLabel(view.model)}</p>
        ) : null}
      </div>
      {view.external ? (
        <Notice tone="warning" data-testid="external-note">
          {EXTERNAL_NOTE}
        </Notice>
      ) : null}
      <Switch
        checked={choice.reasoning}
        disabled={!view.reasoningAvailable}
        onChange={(e) => onChange({ ...choice, reasoning: e.target.checked })}
      >
        Reasoning
        {view.reasoningAvailable ? null : (
          <span className="text-fg-muted">(not available for this model)</span>
        )}
      </Switch>
      <p className="flex items-center gap-1.5 text-meta text-fg-muted">
        <Lock size={14} strokeWidth={1.5} aria-hidden="true" className="shrink-0" />
        These settings cannot be changed once the conversation has started.
      </p>
    </fieldset>
  );
}
