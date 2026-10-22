// P1b-17 (owner decision 2 of Oct 22, 2026): when the conversation's model is down, a
// backup answers: the other EU provider, or, for organisations that allow models served
// outside the EU, one of those. The answer says so.
export function failoverNote(kind: "eu" | "external" | null | undefined): string | null {
  if (kind === "eu") {
    return "This conversation's model was unavailable, so a backup model hosted in the EU answered.";
  }
  if (kind === "external") {
    return (
      "This conversation's model was unavailable, so a backup model served outside the EU " +
      "answered, as your organisation allows."
    );
  }
  return null;
}
