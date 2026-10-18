"""The configured LLM provider picks the client (findings M2)."""

from __future__ import annotations

from pathlib import Path

from app.core.config import load_settings
from app.llm.factory import create_llm_client
from app.llm.mistral import MistralClient
from app.llm.scaleway import ScalewayClient
from tests.test_config import ENV, SCALEWAY_TOML, VALID_TOML, write_config


async def test_mistral_by_default(tmp_path: Path) -> None:
    settings = load_settings(environ=ENV, config_dir=write_config(tmp_path, VALID_TOML))
    client = create_llm_client(settings, "Rewrite.")
    assert isinstance(client, MistralClient)
    await client.aclose()


async def test_scaleway_when_configured(tmp_path: Path) -> None:
    settings = load_settings(environ=ENV, config_dir=write_config(tmp_path, SCALEWAY_TOML))
    client = create_llm_client(settings, "Rewrite.")
    assert isinstance(client, ScalewayClient)
    assert client.chat_model == "deepseek-v4.1-flash"
    await client.aclose()
