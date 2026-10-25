import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Checkbox, Radio } from "./Checkbox";
import { Field } from "./Field";
import { Input, Select, Textarea } from "./Input";
import { Switch } from "./Switch";

const attr = (html: string, tag: string, name: string) =>
  new RegExp(`<${tag}[^>]*\\s${name}="([^"]*)"`).exec(html)?.[1];

describe("Field (UX-07)", () => {
  it("labels its control and links help and error by aria-describedby", () => {
    const html = renderToString(
      <Field label="Days" help="Between 0 and 30." error="Enter a number.">
        <Input />
      </Field>,
    );
    const id = attr(html, "input", "id")!;
    expect(attr(html, "label", "for")).toBe(id);
    expect(attr(html, "input", "aria-describedby")).toBe(`${id}-help ${id}-error`);
    expect(attr(html, "input", "aria-invalid")).toBe("true");
    expect(html).toContain(`id="${id}-help"`);
    expect(html).toContain(`id="${id}-error"`);
  });

  it("without help or error describes nothing and is not invalid", () => {
    const html = renderToString(
      <Field label="Title">
        <Input id="title" />
      </Field>,
    );
    expect(attr(html, "label", "for")).toBe("title");
    expect(html).not.toMatch(/aria-describedby="/);
    expect(html).not.toMatch(/aria-invalid="/);
  });

  it("keeps a description the control already has", () => {
    const html = renderToString(
      <Field label="Code" help="Six digits.">
        <Input id="code" aria-describedby="hint" />
      </Field>,
    );
    expect(attr(html, "input", "aria-describedby")).toBe("hint code-help");
  });
});

describe("controls (UX-07)", () => {
  it("share one 36 px height and the input line, with disabled as a colour state", () => {
    for (const html of [
      renderToString(<Input />),
      renderToString(<Select />),
      renderToString(<Textarea />),
    ]) {
      expect(html).toContain("min-h-9");
      expect(html).toContain("border-line-input");
      expect(html).toContain("disabled:bg-neutral-muted");
      expect(html).not.toMatch(/opacity|px-1\b|p-1\b/);
    }
  });

  it("Checkbox, Radio and Switch are native inputs inside their label", () => {
    expect(renderToString(<Checkbox>Tag</Checkbox>)).toMatch(
      /^<label[^>]*max-sm:min-h-11[^>]*><input type="checkbox"/,
    );
    expect(renderToString(<Radio name="r">Keep</Radio>)).toMatch(/<input type="radio"/);
    expect(renderToString(<Switch>Reasoning</Switch>)).toMatch(
      /<input type="checkbox" role="switch"/,
    );
  });
});
