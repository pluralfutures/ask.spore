"""P0-08: config/tags.toml."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from app.content.models import SOURCE_TYPES
from app.content.tags import SourceType, TagsConfigError, dataset_name, load_tags
from app.core.config import DEFAULT_CONFIG_DIR


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "tags.toml").write_text(text, encoding="utf-8")
    return tmp_path


CLIENT_TAGS = (
    "cc-team1-healthcare-gpo",
    "cc-team2-college-universities",
    "cc-team3-commercial-restaurants",
    "cc-shared",
)


def test_repository_tags_are_the_phase0_tags_with_spec_chunk_methods() -> None:
    tags = load_tags(DEFAULT_CONFIG_DIR)
    assert sorted(tags) == sorted(["sample-analysis", "sample-reports", "sample-web", *CLIENT_TAGS])
    # Spec P0-08: paper for reports, presentation for PPTX, naive for DOCX and web.
    assert tags["sample-reports"].chunk_method_for("pdf") == "paper"
    assert tags["sample-reports"].chunk_method_for("docx") == "naive"
    assert tags["sample-reports"].chunk_method_for("pptx") == "presentation"
    assert tags["sample-analysis"].chunk_method_for("pptx") == "presentation"
    assert tags["sample-analysis"].chunk_method_for("docx") == "naive"
    assert tags["sample-web"].chunk_method_for("markdown") == "naive"


@pytest.mark.parametrize("tag", CLIENT_TAGS)
def test_client_tags_chunk_methods(tag: str) -> None:
    # P1a-04, owner decision Oct 20, 2026 (findings E1).
    config = load_tags(DEFAULT_CONFIG_DIR)[tag]
    assert config.chunk_method_for("pdf") == "paper"
    assert config.chunk_method_for("pptx") == "presentation"
    assert config.chunk_method_for("docx") == "naive"


def test_source_type_literal_matches_schema() -> None:
    assert set(get_args(SourceType)) == set(SOURCE_TYPES)


def test_dataset_name() -> None:
    assert dataset_name("sample-web") == "ask-spore-sample-web"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "tags"),
        ("[tags.a]\nchunk_method = 'nonsense'\n", "chunk_method"),
        ("[tags.a]\nchunk_method = 'naive'\ncolour = 'red'\n", "colour"),
        ("[tags.a]\nchunk_method = 'naive'\nchunk_method_by_type = { exe = 'naive' }\n", "exe"),
        ("[tags.Bad_Tag]\nchunk_method = 'naive'\n", "lowercase-hyphenated"),
        ("[tags.a\n", "not valid TOML"),
    ],
)
def test_invalid_tags_file_is_rejected(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(TagsConfigError, match=message):
        load_tags(write(tmp_path, text))


def test_missing_tags_file(tmp_path: Path) -> None:
    with pytest.raises(TagsConfigError, match="not found"):
        load_tags(tmp_path)
