// Spend figures for the operator console (P1b-12). The API sends euro cents as decimal
// strings, as the usage ledger holds them (fractional cents).

const EUROS = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR" });
const COUNT = new Intl.NumberFormat("en-GB");

export function euros(cents: string | number): string {
  const value = Number(cents);
  return Number.isFinite(value) ? EUROS.format(value / 100) : "–";
}

export function count(value: number): string {
  return COUNT.format(value);
}

// Share of the monthly cap spent, in whole percent; null without a cap.
export function capShare(spentCents: string | number, capCents: number | null): number | null {
  if (capCents === null) return null;
  if (capCents === 0) return 100;
  return Math.floor((Number(spentCents) * 100) / capCents);
}
