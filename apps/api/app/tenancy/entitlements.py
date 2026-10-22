"""What the operator may enable for a tenant (P1a-03), and the model entitlement check
(P1a-09).

``available_models`` lists the catalogue in ``config/models.toml`` (P1a-09). The check
``check_choice`` runs before any outbound call for a conversation: a model that is not
in the catalogue, not in the tenant's ``enabled_models``, or external while the tenant's
``external_models_enabled`` is false is refused, and so is reasoning on a model
without a reasoning switch. Refusals carry a short code that is safe to log and show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import CatalogueEntry, Settings
from app.llm import catalogue
from app.llm.catalogue import ModelChoice
from app.tenancy.models import ANSWER_MODES, TenantEntitlements

RefusalCode = Literal[
    "model_unavailable",
    "model_not_enabled",
    "external_not_entitled",
    "reasoning_unsupported",
    "spend_cap_reached",
]


class ModelRefused(Exception):
    """The tenant may not use this model choice. ``code`` is safe to log and to show."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


@dataclass(frozen=True)
class ModelEntitlement:
    """The part of ``tenant_entitlements`` the model check reads."""

    enabled_models: tuple[str, ...]
    external_models_enabled: bool
    external_spend_cap_cents: int | None
    # The client's signed acceptance (P1a-03); the failover to OpenRouter needs it on
    # file (P1b-17), as the database already does for the switch itself.
    external_acceptance_reference: str | None = None

    @classmethod
    def of(cls, row: TenantEntitlements | None) -> ModelEntitlement:
        if row is None:  # no row: nothing is enabled (fail closed)
            return cls((), False, None)
        return cls(
            tuple(row.enabled_models),
            bool(row.external_models_enabled),
            row.external_spend_cap_cents,
            row.external_acceptance_reference,
        )


def available_models(settings: Settings) -> tuple[str, ...]:
    """Every catalogue model, in catalogue order (the operator console's choices)."""
    return tuple(e.id for e in catalogue.entries(settings))


def default_model(settings: Settings) -> str:
    """What a new tenant gets enabled: the platform default model."""
    return catalogue.platform_default(settings)


def available_answer_modes() -> tuple[str, ...]:
    return ANSWER_MODES


def usable_models(settings: Settings, ent: ModelEntitlement) -> tuple[CatalogueEntry, ...]:
    """The tenant's enabled models that the entitlement lets it call, in catalogue order."""
    return tuple(
        e
        for e in catalogue.entries(settings)
        if e.id in ent.enabled_models and (ent.external_models_enabled or not e.external)
    )


def eu_fallback_choice(settings: Settings, ent: ModelEntitlement) -> ModelChoice | None:
    """The model choice when the workspace's default cannot be used (findings C1).

    The platform default if the tenant has it enabled, else the tenant's first enabled
    EU model in catalogue order, with reasoning off. Never an external model, so it is
    also the spend-cap fallback when the workspace default is external. None when the
    tenant has no EU model enabled.
    """
    eu = [e.id for e in usable_models(settings, ent) if not e.external]
    if not eu:
        return None
    platform = catalogue.platform_default(settings)
    return ModelChoice(platform if platform in eu else eu[0], reasoning=False)


def check_choice(settings: Settings, ent: ModelEntitlement, choice: ModelChoice) -> CatalogueEntry:
    """The catalogue entry for ``choice``, or ``ModelRefused``. No I/O, no outbound call."""
    model = catalogue.entry(settings, choice.model)
    if model is None:
        raise ModelRefused("model_unavailable")
    if model.id not in ent.enabled_models:
        raise ModelRefused("model_not_enabled")
    if model.external and not ent.external_models_enabled:
        raise ModelRefused("external_not_entitled")
    if choice.reasoning and not model.can_reason:
        raise ModelRefused("reasoning_unsupported")
    return model
