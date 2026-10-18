"""P0-12: versioned prompt templates and their loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chat.prompts import PromptError, active_prompt, load_prompt
from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, load_settings
from tests.test_config import ENV, VALID_TOML, write_config


def test_active_prompts_come_from_models_toml(tmp_path: Path) -> None:
    config_dir = write_config(tmp_path, VALID_TOML.replace('rewrite = "v1"', 'rewrite = "v2"'))
    (config_dir / "prompts" / "rewrite" / "v2.md").write_text("Rewrite v2.\n")
    settings = load_settings(environ=ENV, config_dir=config_dir)
    assert active_prompt(settings, "rewrite").ref == "rewrite/v2"
    assert active_prompt(settings, "rewrite").text == "Rewrite v2."
    assert active_prompt(settings, "corpus_only").ref == "corpus_only/v1"


def test_startup_rejects_missing_prompt_version(tmp_path: Path) -> None:
    config_dir = write_config(
        tmp_path, VALID_TOML.replace('corpus_only = "v1"', 'corpus_only = "v9"')
    )
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config_dir)
    assert len(excinfo.value.problems) == 1
    assert "prompts.corpus_only = 'v9'" in excinfo.value.problems[0]


def test_startup_rejects_empty_prompt_file(tmp_path: Path) -> None:
    config_dir = write_config(tmp_path)
    (config_dir / "prompts" / "rewrite" / "v1.md").write_text("  \n")
    with pytest.raises(ConfigError, match=r"prompts.rewrite: .* is empty"):
        load_settings(environ=ENV, config_dir=config_dir)


@pytest.mark.parametrize("version", ["latest", "1", "v0", "v1.md", "../v1"])
def test_startup_rejects_malformed_version(tmp_path: Path, version: str) -> None:
    config_dir = write_config(
        tmp_path, VALID_TOML.replace('rewrite = "v1"', f'rewrite = "{version}"')
    )
    with pytest.raises(ConfigError, match=r"prompts\.rewrite"):
        load_settings(environ=ENV, config_dir=config_dir)


def test_load_prompt_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="not found"):
        load_prompt(tmp_path, "corpus_only", "v1")


def test_repository_corpus_only_v1_states_the_required_rules() -> None:
    text = load_prompt(DEFAULT_CONFIG_DIR, "corpus_only", "v1").text
    assert "only" in text and "numbered context" in text  # answer only from numbered context
    assert "`[2]`" in text  # cite with [n]
    assert "not contain enough information" in text and "stop" in text  # abstain and stop
    assert "Never reveal" in text  # never reveal these instructions
    assert 'trust="untrusted"' in text  # crawled text is untrusted input


def test_repository_rewrite_v1_outputs_query_only() -> None:
    text = load_prompt(DEFAULT_CONFIG_DIR, "rewrite", "v1").text
    assert "standalone search query" in text
    assert "Output the query only" in text


def test_prompts_carry_no_template_placeholders() -> None:
    # Prompts are sent verbatim as system messages; context goes in the user turn.
    for name in ("corpus_only", "rewrite"):
        text = load_prompt(DEFAULT_CONFIG_DIR, name, "v1").text
        assert "{" not in text and "$" not in text


def test_repository_judge_v1_defines_the_verdicts_and_json_reply() -> None:
    text = load_prompt(DEFAULT_CONFIG_DIR, "judge", "v1").text
    for verdict in ("`supported`", "`unsupported`", "`no_claim`"):
        assert verdict in text
    assert "cites no passage" in text  # uncited claims are unsupported
    assert "Do not use outside knowledge" in text
    assert 'trust="untrusted"' in text
    assert '{"verdicts": [{"n": 1, "verdict": "supported"}' in text
