import { Download, Plus, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react";
import { MemoryRouter } from "react-router-dom";

import { Button, ButtonLink } from "./Button";
import type { ButtonSize, ButtonVariant } from "./buttonClass";
import { IconButton } from "./IconButton";
import { LINK } from "./link";

// UX-06: the development-only component gallery at /_ui (App.tsx loads it only when
// import.meta.env.DEV). The visual suite captures it, so a component change shows up in
// one snapshot before it shows up across the screens.

const VARIANTS: ButtonVariant[] = [
  "primary",
  "secondary",
  "ghost",
  "danger",
  "secondary-danger",
  "ghost-danger",
];
const SIZES: ButtonSize[] = ["sm", "md", "lg"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-control border bg-surface p-4">
      <h2 className="mb-3 text-heading font-strong">{title}</h2>
      {children}
    </section>
  );
}

export default function Gallery() {
  return (
    <MemoryRouter>
      <main data-testid="ui-gallery" className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4">
        <h1 className="text-title font-strong">Components</h1>
        <Section title="Button">
          <div className="overflow-x-auto">
            <table className="text-ui">
              <thead>
                <tr>
                  <th className="pr-4 text-left text-fg-muted">Variant</th>
                  {SIZES.map((size) => (
                    <th key={size} className="px-2 text-left text-fg-muted">
                      {size}
                    </th>
                  ))}
                  <th className="px-2 text-left text-fg-muted">Disabled</th>
                </tr>
              </thead>
              <tbody>
                {VARIANTS.map((variant) => (
                  <tr key={variant}>
                    <td className="pr-4">{variant}</td>
                    {SIZES.map((size) => (
                      <td key={size} className="p-2">
                        <Button variant={variant} size={size}>
                          Save
                        </Button>
                      </td>
                    ))}
                    <td className="p-2">
                      <Button variant={variant} disabled>
                        Save
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section title="With an icon, pressed, and as a link">
          <div className="flex flex-wrap items-center gap-2">
            <ButtonLink to="/new" variant="primary" icon={Plus}>
              New conversation
            </ButtonLink>
            <Button icon={Download}>Download audit log</Button>
            <Button variant="ghost-danger" size="sm" icon={Trash2}>
              Delete
            </Button>
            <Button size="sm" icon={ThumbsUp} aria-pressed>
              Helpful
            </Button>
            <Button size="sm" icon={ThumbsDown} aria-pressed={false}>
              Not helpful
            </Button>
          </div>
        </Section>
        <Section title="IconButton">
          <div className="flex items-center gap-2">
            <IconButton label="Close" icon={X} size="sm" />
            <IconButton label="Close" icon={X} />
            <IconButton label="Close" icon={X} variant="secondary" />
            <IconButton label="Close" icon={X} variant="secondary" disabled />
          </div>
        </Section>
        <Section title="Link">
          <p className="text-ui">
            Inline links are underlined, for example{" "}
            <a href="#link" className={LINK}>
              View at source
            </a>
            .
          </p>
        </Section>
      </main>
    </MemoryRouter>
  );
}
