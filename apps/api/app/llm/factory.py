"""The LLM client for the configured provider (``[llm] provider``, findings M2)."""

from __future__ import annotations

from app.core.config import Settings
from app.llm.mistral import MistralClient
from app.llm.scaleway import ScalewayClient

LLMClient = MistralClient | ScalewayClient


def create_llm_client(settings: Settings, rewrite_system: str) -> LLMClient:
    """Startup checks guarantee the active provider's section and key are present."""
    models, secrets = settings.models, settings.secrets
    if models.llm.provider == "scaleway":
        if models.scaleway is None or secrets.scaleway_api_key is None:
            raise RuntimeError("scaleway provider without config or key")  # load_settings
        return ScalewayClient(
            models.scaleway,
            secrets.scaleway_api_key,
            rewrite_system,
            project_id=secrets.scaleway_project_id,
        )
    if secrets.mistral_api_key is None:
        raise RuntimeError("mistral provider without key")  # load_settings checks it
    return MistralClient(models.mistral, secrets.mistral_api_key, rewrite_system)
