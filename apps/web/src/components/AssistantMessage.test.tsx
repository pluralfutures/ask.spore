import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AssistantMessage } from "./AssistantMessage";

const render = (extra: Partial<Parameters<typeof AssistantMessage>[0]> = {}) =>
  renderToString(
    <AssistantMessage
      text="Synthetic answer."
      citations={[]}
      unsupported={false}
      abstained={false}
      messageId="m1"
      onCite={() => {}}
      {...extra}
    />,
  );

// UX-15: the answer block holds its notes under the text and its feedback in a footer.
describe("AssistantMessage (UX-15)", () => {
  it("puts the notes inside the block, after the text and before the footer", () => {
    const html = render({ notes: <p>Synthetic note</p> });
    const text = html.indexOf("Synthetic answer.");
    const note = html.indexOf("Synthetic note");
    const footer = html.indexOf("<footer");
    expect(html.startsWith("<article")).toBe(true);
    expect(text).toBeLessThan(note);
    expect(note).toBeLessThan(footer);
    expect(html.slice(footer)).toContain("Helpful");
  });

  it("has no footer while the answer streams", () => {
    expect(render({ messageId: null })).not.toContain("<footer");
  });

  it("keeps notes inside a 'nothing relevant found' block too", () => {
    const html = render({ abstained: true, notes: <p>Synthetic note</p> });
    expect(html).toContain('data-testid="nothing-found"');
    expect(html.indexOf("Synthetic note")).toBeLessThan(html.indexOf("<footer"));
  });

  it("renders the model's top heading below the page's h1", () => {
    const html = render({ text: "# Summary\n\nSynthetic answer." });
    expect(html).not.toContain("<h1");
    expect(html).toContain("<h2>Summary</h2>");
  });
});
