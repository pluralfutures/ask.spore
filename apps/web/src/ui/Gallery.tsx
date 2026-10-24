import { Download, Plus, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react";
import { MemoryRouter } from "react-router-dom";

import { Button, ButtonLink } from "./Button";
import type { ButtonSize, ButtonVariant } from "./buttonClass";
import { Badge, StatusBadge } from "./Badge";
import { Card } from "./Card";
import { Checkbox, Radio } from "./Checkbox";
import { Field } from "./Field";
import { IconButton } from "./IconButton";
import { Input, Select, Textarea } from "./Input";
import { LINK } from "./link";
import { Notice } from "./Notice";
import { PageHeader } from "./PageHeader";
import { EmptyState, Loading, Skeleton } from "./States";
import { Switch } from "./Switch";

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
        <Section title="Form controls">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Title">
              <Input defaultValue="Synthetic market outlook" />
            </Field>
            <Field label="Days" help="Between 0 and 30.">
              <Input type="number" defaultValue={30} className="w-20" />
            </Field>
            <Field label="Licence basis" error="Enter a licence basis.">
              <Input />
            </Field>
            <Field label="Disabled">
              <Input defaultValue="Read only" disabled />
            </Field>
            <Field label="Model">
              <Select defaultValue="eu">
                <option value="eu">Synthetic EU Standard</option>
                <option value="fast">Synthetic EU Fast</option>
              </Select>
            </Field>
            <Field label="File">
              <Input type="file" />
            </Field>
            <Field label="Allowed paths" help="One pattern per line." className="sm:col-span-2">
              <Textarea defaultValue={"/reports/*\n/notes/*"} />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap gap-6">
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-ui font-strong">Checkbox</legend>
              <Checkbox defaultChecked>Synthetic tag A</Checkbox>
              <Checkbox>Synthetic tag B</Checkbox>
              <Checkbox disabled>Disabled</Checkbox>
            </fieldset>
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-ui font-strong">Radio</legend>
              <Radio name="gallery-radio" defaultChecked>
                Keep both
              </Radio>
              <Radio name="gallery-radio">Replace</Radio>
            </fieldset>
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-ui font-strong">Switch</legend>
              <Switch defaultChecked>Reasoning</Switch>
              <Switch>Sign-in links</Switch>
              <Switch disabled>Disabled</Switch>
            </fieldset>
          </div>
        </Section>
        <Section title="Surfaces and feedback">
          <div className="flex flex-col gap-4">
            <PageHeader
              back={{ to: "/", label: "← Conversations" }}
              title="Page title"
              description="One line that says what the page is for."
              actions={<Button variant="primary">Primary action</Button>}
              meta={<StatusBadge kind="tenant" status="active" />}
            />
            <Card
              title="Card title"
              description="Optional description."
              actions={<Button size="sm">Edit</Button>}
            >
              <p className="text-ui">Card content.</p>
            </Card>
            <div className="flex flex-wrap gap-2">
              <Badge>neutral</Badge>
              <Badge tone="accent">accent</Badge>
              <Badge tone="warning">warning</Badge>
              <Badge tone="danger">danger</Badge>
              <Badge tone="success">success</Badge>
              <StatusBadge kind="source" status="ingested" />
              <StatusBadge kind="source" status="failed" />
              <StatusBadge kind="user" status="invited" />
            </div>
            <Notice>An information notice.</Notice>
            <Notice tone="warning" title="Warning title">
              A warning notice with a title.
            </Notice>
            <Notice tone="danger">An error notice.</Notice>
            <Notice tone="success">A success notice.</Notice>
            <Loading />
            <Skeleton rows={2} />
            <EmptyState title="Nothing here yet." action={<Button size="sm">Add one</Button>} />
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
