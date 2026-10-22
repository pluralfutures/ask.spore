import type { EntitlementsIn, EntitlementsOut } from "../api/types";

// The operator's entitlement form (P1a-03), and the request it becomes.
export interface EntitlementsForm {
  answerModes: string[];
  enabledModels: string[];
  externalModelsEnabled: boolean;
  spendCapEuros: string;
  acceptanceReference: string;
  acceptanceDate: string;
}

export function formFrom(current: EntitlementsOut): EntitlementsForm {
  return {
    answerModes: current.answer_modes,
    enabledModels: current.enabled_models,
    externalModelsEnabled: current.external_models_enabled,
    spendCapEuros:
      current.external_spend_cap_cents === null
        ? ""
        : String(current.external_spend_cap_cents / 100),
    acceptanceReference: "",
    acceptanceDate: "",
  };
}

// Mirrors the API's rules so the operator sees the reason before saving: switching
// external models on needs the client's acceptance (DPA document and date) and a cap.
// P1b-12 (Phase 1a findings F2): the save names the tenant of the page it was made on,
// both in the path and in the body; the API refuses it when the two differ.
export function toRequest(
  pageTenantId: string,
  form: EntitlementsForm,
  current: EntitlementsOut,
): { tenantId: string; body: EntitlementsIn } | { error: string } {
  const cap =
    form.spendCapEuros.trim() === "" ? null : Math.round(Number(form.spendCapEuros) * 100);
  if (cap !== null && (!Number.isFinite(cap) || cap < 0))
    return { error: "Spend cap must be a number." };
  const reference = form.acceptanceReference.trim();
  const acceptance =
    reference && form.acceptanceDate ? { reference, accepted_on: form.acceptanceDate } : null;
  if (form.externalModelsEnabled) {
    if (cap === null) return { error: "External models need a monthly spend cap." };
    if (acceptance === null && !current.external_models_enabled) {
      return { error: "External models need the client's acceptance: DPA document and date." };
    }
  }
  return {
    tenantId: pageTenantId,
    body: {
      tenant_id: pageTenantId,
      answer_modes: form.answerModes as EntitlementsIn["answer_modes"],
      enabled_models: form.enabledModels,
      external_models_enabled: form.externalModelsEnabled,
      external_spend_cap_cents: cap,
      external_acceptance: acceptance,
    },
  };
}
