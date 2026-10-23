"""P0-08: config/tags.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import get_args

import pytest

from app.content.models import SOURCE_TYPES
from app.content.tags import (
    PDF_ONLY_METHODS,
    SourceType,
    TagConfig,
    TagsConfigError,
    dataset_name,
    load_tags,
    tags_for_tenant,
)
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
    # Findings E6: "paper" parses PDF only; a Markdown row failed in the Oct 20 ingestion.
    assert config.chunk_method_for("markdown") == "naive"
    assert config.chunk_method_for("html") == "naive"


@pytest.mark.parametrize("method", ["paper", "manual"])
def test_pdf_only_default_needs_an_override_for_every_other_type(
    tmp_path: Path, method: str
) -> None:
    text = (
        f"[tags.a]\nchunk_method = '{method}'\nshared = true\n"
        "chunk_method_by_type = { docx = 'naive', pptx = 'presentation', html = 'naive' }\n"
    )
    with pytest.raises(TagsConfigError, match=r"\['markdown'\].*PDF-only"):
        load_tags(write(tmp_path, text))
    covered = text.replace("html = 'naive'", "html = 'naive', markdown = 'naive'")
    assert load_tags(write(tmp_path, covered))["a"].chunk_method_for("markdown") == "naive"


def test_every_repository_tag_parses_every_source_type() -> None:
    for tag, config in load_tags(DEFAULT_CONFIG_DIR).items():
        for source_type in SOURCE_TYPES:
            if source_type != "pdf":
                assert config.chunk_method_for(source_type) not in PDF_ONLY_METHODS, (
                    tag,
                    source_type,
                )


def test_source_type_literal_matches_schema() -> None:
    assert set(get_args(SourceType)) == set(SOURCE_TYPES)


def test_dataset_name() -> None:
    assert dataset_name("sample-web") == "ask-spore-sample-web"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "tags"),
        ("[tags.a]\nchunk_method = 'nonsense'\nshared = true\n", "chunk_method"),
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


def test_shared_tags_are_offered_to_every_tenant_and_own_tags_to_one(tmp_path: Path) -> None:
    tags = load_tags(
        write(
            tmp_path,
            '[tags.common]\nchunk_method = "naive"\nshared = true\n'
            '[tags.a-own]\nchunk_method = "naive"\ntenant = "a"\n'
            '[tags.b-own]\nchunk_method = "naive"\ntenant = "b"\n',
        )
    )
    assert tags_for_tenant(tags, "a") == ["a-own", "common"]
    assert tags_for_tenant(tags, "b") == ["b-own", "common"]
    assert tags_for_tenant(tags, "c") == ["common"]


def test_repository_sample_tags_belong_to_the_internal_tenant() -> None:
    # Owner decision of Oct 22, 2026 (Phase 1b release 5.1): no client is offered them.
    tags = load_tags(DEFAULT_CONFIG_DIR)
    assert tags_for_tenant(tags, "cc") == sorted(CLIENT_TAGS)
    assert tags_for_tenant(tags, "internal") == ["sample-analysis", "sample-reports", "sample-web"]


# --- P1c-01: an unset tenant is never shared by omission -----------------------------------


def test_a_file_relying_on_the_old_shared_default_is_refused(tmp_path: Path) -> None:
    text = '[tags.a]\nchunk_method = "naive"\n[tags.b]\nchunk_method = "naive"\ntenant = "cc"\n'
    with pytest.raises(TagsConfigError, match=r"\['a'\] name no tenant"):
        load_tags(write(tmp_path, text))


def test_a_tag_cannot_be_both_a_tenants_and_shared(tmp_path: Path) -> None:
    text = '[tags.a]\nchunk_method = "naive"\ntenant = "cc"\nshared = true\n'
    with pytest.raises(TagsConfigError, match="both tenant and shared"):
        load_tags(write(tmp_path, text))


def test_a_tag_without_a_tenant_is_never_on_a_client_picker() -> None:
    # Built in code (the loader refuses such a file): it falls to the internal tenant.
    tags = {
        "unset": TagConfig(chunk_method="naive"),
        "own": TagConfig(chunk_method="naive", tenant="cc"),
    }
    assert tags["unset"].owner == "internal"
    assert tags_for_tenant(tags, "cc") == ["own"]
    assert tags_for_tenant(tags, "other") == []
    assert tags_for_tenant(tags, "internal") == ["unset"]


def test_every_repository_tag_names_its_owner_or_is_marked_shared() -> None:
    raw = tomllib.loads((DEFAULT_CONFIG_DIR / "tags.toml").read_text(encoding="utf-8"))
    for tag, table in raw["tags"].items():
        assert ("tenant" in table) != bool(table.get("shared")), tag
