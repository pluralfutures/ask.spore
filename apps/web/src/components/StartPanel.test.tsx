import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationDetail, ModelOption, Workspace } from "../api/types";
import {
  createBody,
  initialChoice,
  panelView,
  refusalText,
  selectModel,
  selectWorkspace,
} from "../lib/startPanel";
import { ConversationHeader } from "./ConversationHeader";
import { StartPanel } from "./StartPanel";

// Synthetic options only (CLAUDE.md).
const workspace = (id: string, name: string, model: string, reasoning = false): Workspace => ({
  id,
  slug: id,
  name,
  default_mode: "corpus_only",
  default_model: model,
  default_reasoning: reasoning,
});
const model = (id: string, extra: Partial<ModelOption> = {}): ModelOption => ({
  id,
  display_name: id.toUpperCase(),
  external: false,
  reasoning_switch: true,
  default: false,
  ...extra,
});

const ALPHA = workspace("ws-alpha", "Alpha team", "eu-fast");
const BETA = workspace("ws-beta", "Beta team", "ext-large", true);
const EU = model("eu-fast", { default: true });
const EU_PLAIN = model("eu-plain", { reasoning_switch: false });
const EXTERNAL = model("ext-large", { display_name: "Large External", external: true });

function render(
  workspaces: Workspace[],
  models: ModelOption[],
  choice = initialChoice(workspaces, models),
) {
  return renderToString(
    <StartPanel workspaces={workspaces} models={models} choice={choice} onChange={() => {}} />,
  );
}

describe("start panel state", () => {
  it("pre-fills model and reasoning from the workspace defaults", () => {
    expect(initialChoice([ALPHA, BETA], [EU, EXTERNAL])).toEqual({
      workspaceId: "ws-alpha",
      model: "eu-fast",
      reasoning: false,
    });
    expect(selectWorkspace("ws-beta", [ALPHA, BETA], [EU, EXTERNAL])).toEqual({
      workspaceId: "ws-beta",
      model: "ext-large",
      reasoning: true,
    });
  });

  it("falls back to the tenant default when the workspace default is not offered", () => {
    expect(selectWorkspace("ws-beta", [ALPHA, BETA], [EU_PLAIN, EU]).model).toBe("eu-fast");
    expect(initialChoice([BETA], [EU_PLAIN]).model).toBe("eu-plain");
  });

  it("switches reasoning off for a model without a switch", () => {
    const choice = selectWorkspace("ws-beta", [ALPHA, BETA], [EU_PLAIN, EXTERNAL]);
    expect(choice.reasoning).toBe(true);
    const plain = selectModel(choice, "eu-plain", [EU_PLAIN, EXTERNAL]);
    expect(plain.reasoning).toBe(false);
    expect(panelView(plain, [BETA], [EU_PLAIN, EXTERNAL]).reasoningAvailable).toBe(false);
  });

  it("sends only the user's choice, never dataset or document IDs", () => {
    const body = createBody({ workspaceId: "ws-beta", model: "ext-large", reasoning: true });
    expect(body).toEqual({ workspace_id: "ws-beta", model: "ext-large", reasoning: true });
  });

  it("explains a refusal in plain words", () => {
    expect(refusalText("workspace_required")).toBe("Choose a workspace.");
    expect(refusalText(null)).toBe("The conversation could not be started.");
  });
});

describe("StartPanel", () => {
  it("hides the workspace chooser when the tenant has one workspace", () => {
    const html = render([ALPHA], [EU, EXTERNAL]);
    expect(html).not.toContain("<select><option");
    expect(html).toContain("Workspace: <!-- -->Alpha team");
    expect(html.match(/<select/g)).toHaveLength(1); // the model chooser only
  });

  it("shows both choosers when there are several workspaces and models", () => {
    const html = render([ALPHA, BETA], [EU, EXTERNAL]);
    expect(html.match(/<select/g)).toHaveLength(2);
    expect(html).toContain("Alpha team");
    expect(html).toContain("Beta team");
  });

  it("hides the model chooser when one model is enabled", () => {
    const html = render([ALPHA, BETA], [EU]);
    expect(html.match(/<select/g)).toHaveLength(1);
    expect(html).not.toContain("Model");
  });

  it("marks external models as served outside the EU in plain words", () => {
    const html = render([ALPHA], [EU, EXTERNAL]);
    expect(html).toContain("Large External (served outside the EU)");
    expect(html).not.toContain("EU-FAST (served");
    expect(html).not.toContain("external-note");
    const chosen = render([BETA], [EU, EXTERNAL]);
    expect(chosen).toContain("This model is served outside the EU.");
  });

  it("states that an external model is served outside the EU even with no chooser", () => {
    const html = render([ALPHA], [EXTERNAL]);
    expect(html).not.toContain("<select");
    expect(html).toContain("This model is served outside the EU.");
  });

  it("renders the reasoning toggle checked, or disabled for a model without a switch", () => {
    const on = render([BETA], [EU, EXTERNAL]);
    // UX-07: reasoning is a switch (a checkbox with role="switch").
    expect(on).toMatch(/<input type="checkbox" role="switch"[^>]*\schecked=""/);
    const plain = render([ALPHA], [EU_PLAIN]);
    expect(plain).toMatch(/<input type="checkbox" role="switch"[^>]*\sdisabled=""/);
    expect(plain).toContain("not available for this model");
  });
});

describe("ConversationHeader", () => {
  const conversation: ConversationDetail = {
    id: "c1",
    title: null,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    expires_at: "2026-11-18T10:00:00Z",
    workspace_id: "ws-beta",
    workspace_name: "Beta team",
    mode: "corpus_only",
    model: "ext-large",
    model_display_name: "Large External",
    reasoning: true,
    messages: [],
  };

  it("shows workspace label, model name and the reasoning badge, read-only", () => {
    const html = renderToString(<ConversationHeader conversation={conversation} />);
    expect(html).toContain("Beta team");
    expect(html).toContain("Large External");
    expect(html).toContain("Reasoning on");
    expect(html).not.toMatch(/<(select|input|button)/);
  });

  it("shows no badge with reasoning off", () => {
    const html = renderToString(
      <ConversationHeader conversation={{ ...conversation, reasoning: false }} />,
    );
    expect(html).not.toContain("Reasoning on");
  });
});
