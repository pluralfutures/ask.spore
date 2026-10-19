"""The model catalogue (P1a-09): which models exist, who serves them, what they cost.

Read from ``config/models.toml`` ``[[catalogue]]``, validated at startup
(``app.core.config``). A ``ModelChoice`` is what a conversation fixes when it starts:
a catalogue model and the reasoning switch. It names no tenant, user or workspace and
is the only model input the LLM client factory and the usage recorder take.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import CatalogueEntry, Settings, default_models
from app.core.logging import log

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelChoice:
    """A conversation's model (a catalogue ``id``) and its reasoning switch (P1a-11)."""

    model: str
    reasoning: bool


def entries(settings: Settings) -> tuple[CatalogueEntry, ...]:
    return settings.models.catalogue


def entry(settings: Settings, model: str) -> CatalogueEntry | None:
    return next((e for e in settings.models.catalogue if e.id == model), None)


def platform_default(settings: Settings) -> str:
    """The active provider's chat model: never external, the eval model (architecture §14.2)."""
    return default_models(settings.models)[0]


def default_choice(settings: Settings) -> ModelChoice:
    """Reasoning off, as Phase 0 answered and as the eval baseline runs (findings M2)."""
    return ModelChoice(platform_default(settings), reasoning=False)


def warn_placeholder_prices(settings: Settings) -> None:
    """Log a warning per catalogue entry whose prices are placeholders (metadata only:
    the model, never the figures). The usage ledger and spend cap price from them."""
    for e in settings.models.catalogue:
        if e.price_placeholder:
            log("config.price_placeholder", level="warning", model=e.id)


def external_ids(settings: Settings) -> tuple[str, ...]:
    return tuple(e.id for e in settings.models.catalogue if e.external)


def cost_cents(model: CatalogueEntry, tokens_in: int, tokens_out: int) -> Decimal:
    """Price one call from the catalogue, in euro cents (fractional, not rounded)."""
    price_in = Decimal(str(model.price_in_cents_per_mtok))
    price_out = Decimal(str(model.price_out_cents_per_mtok))
    return (price_in * tokens_in + price_out * tokens_out) / MILLION
