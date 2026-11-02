// P2B-03: the conversation search runs in the browser over the list the API already
// returned, so the query reaches no server and no log (owner decision 2). Titles only.

export const UNTITLED = "Untitled conversation";

// Case and accents ignored: "Cafe" finds "Café".
function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function matchesTitle(title: string | null, query: string): boolean {
  const wanted = fold(query);
  return wanted === "" || fold(title ?? UNTITLED).includes(wanted);
}
