import { errorText } from "../lib/operator";
import { Notice } from "../ui/Notice";

// P1c-08: every operator console save says how it went: "Saved." once the API accepted
// it, or the refusal in words. Pass the mutation's state; nothing shows before a save.
export function SaveStatus({
  isSuccess,
  error,
  savedText = "Saved.",
}: {
  isSuccess: boolean;
  error: unknown;
  savedText?: string;
}) {
  const problem = errorText(error);
  if (problem)
    return (
      <Notice tone="danger" className="w-full">
        {problem}
      </Notice>
    );
  if (isSuccess) {
    return (
      <p role="status" className="w-full text-success">
        {savedText}
      </p>
    );
  }
  return null;
}
