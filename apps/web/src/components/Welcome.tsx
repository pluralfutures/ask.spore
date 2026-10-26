import { cardClass } from "../ui/cardClass";
import { Button } from "../ui/Button";
import { ProductName } from "./ProductName";

interface Step {
  title: string;
  text: string;
}

const PICK: Step = {
  title: "Pick a workspace",
  text: "Each one covers a different set of sources.",
};
const STEPS: Step[] = [
  {
    title: "Ask a specific question",
    text: "Name a product, region or period for sharper answers.",
  },
  {
    title: "Check the citations",
    text: "Click a number to see the excerpt and where it comes from.",
  },
];

// HP-03: the home page's welcome card, wording approved by the owner on Oct 26, 2026
// (home page spec, "Wording"). "Pick a workspace" only when there is a choice to make.
export function Welcome({
  workspaceCount,
  onHide,
}: {
  workspaceCount: number;
  onHide: () => void;
}) {
  const steps = workspaceCount > 1 ? [PICK, ...STEPS] : STEPS;
  return (
    <section aria-labelledby="welcome-title" className={cardClass("flex flex-col gap-5 p-6")}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 id="welcome-title" className="text-display font-strong">
            Welcome to <ProductName />
          </h1>
          <p className="max-w-xl text-reading text-fg-secondary">
            Ask research questions in plain language. SporeBot searches your workspace&apos;s
            sources and cites them, so you can check each claim.
          </p>
        </div>
        <Button className="shrink-0" aria-label="Hide the welcome" onClick={onHide}>
          Hide
        </Button>
      </div>
      <ol className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {steps.map((step, i) => (
          <li key={step.title} className="flex gap-3">
            <span
              aria-hidden="true"
              className="flex size-7 shrink-0 items-center justify-center rounded-control bg-info-subtle text-ui font-strong text-info"
            >
              {i + 1}
            </span>
            <div className="text-ui">
              <p className="font-strong">{step.title}</p>
              <p className="mt-1 text-fg-muted">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="border-t pt-4 text-meta text-fg-muted">
        Conversations are deleted automatically, after 30 days at most.
      </p>
    </section>
  );
}
