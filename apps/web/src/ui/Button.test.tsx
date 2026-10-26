import { X } from "lucide-react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Button, ButtonLink } from "./Button";
import { buttonClass } from "./buttonClass";
import { IconButton } from "./IconButton";

describe("Button (UX-06)", () => {
  it("is type=button unless told otherwise, so it never submits a form by accident", () => {
    expect(renderToString(<Button>Save</Button>)).toContain('type="button"');
    expect(renderToString(<Button type="submit">Save</Button>)).toContain('type="submit"');
  });

  it("shows disabled as a colour state, never opacity", () => {
    for (const variant of ["primary", "secondary", "danger", "secondary-danger"] as const) {
      const classes = buttonClass(variant);
      expect(classes).toContain("disabled:bg-neutral-muted");
      expect(classes).toContain("disabled:text-fg-muted");
      expect(classes).not.toMatch(/opacity/);
    }
    expect(buttonClass("ghost")).not.toMatch(/opacity/);
  });

  it("reaches the 44 px touch target on phone at every size", () => {
    for (const size of ["sm", "md", "lg"] as const) {
      expect(buttonClass("primary", size)).toContain("max-sm:min-h-11");
    }
  });

  it("keeps layout classes passed by the caller", () => {
    expect(buttonClass("primary", "md", "w-fit self-end")).toMatch(/ w-fit self-end$/);
  });

  it("hides its icon from assistive technology; the text is the name", () => {
    const html = renderToString(<Button icon={X}>Close</Button>);
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
    expect(html).toContain(">Close</button>");
  });

  it("ButtonLink is a link styled as a button", () => {
    const html = renderToString(
      <MemoryRouter>
        <ButtonLink to="/new" variant="primary">
          New conversation
        </ButtonLink>
      </MemoryRouter>,
    );
    expect(html).toMatch(/^<a [^>]*href="\/new"/);
    expect(html).toContain("bg-primary");
  });
});

describe("IconButton (UX-06)", () => {
  it("uses its required label as the accessible name and the tooltip", () => {
    const html = renderToString(<IconButton label="Close" icon={X} />);
    expect(html).toContain('aria-label="Close"');
    expect(html).toContain('title="Close"');
    expect(html).toContain("max-sm:size-11");
  });
});
