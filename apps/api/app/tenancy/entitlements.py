"""What the operator may enable for a tenant (P1a-03).

``available_models`` is a STUB until P1a-09 adds the model catalogue to
``config/models.toml``: until then the only model is the active provider's chat model,
and external models cannot be listed (their entitlement switch can be set, with the
client's acceptance, but enables nothing yet).
"""

from __future__ import annotations

from app.core.config import Settings
from app.tenancy.models import ANSWER_MODES


def available_models(settings: Settings) -> tuple[str, ...]:
    models = settings.models
    if models.llm.provider == "scaleway" and models.scaleway is not None:
        return (models.scaleway.chat_model,)
    return (models.mistral.chat_model,)


def default_model(settings: Settings) -> str:
    return available_models(settings)[0]


def available_answer_modes() -> tuple[str, ...]:
    return ANSWER_MODES
