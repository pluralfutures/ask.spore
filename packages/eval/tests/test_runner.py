"""P0-18: harness settings, the RAGFlow URL override and per-item pipeline records."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import DEFAULT_CONFIG_DIR

from eval.pipeline import Citation, PipelineAnswer
from eval.runner import HarnessError, load_harness_settings, pipeline_record, with_ragflow_url
from eval.schema import EvalItem

ENV = {
    "MISTRAL_API_KEY": "k",
    "RAGFLOW_API_KEY": "k",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "PHASE0_BEARER_TOKEN": "t" * 32,
}


def settings():  # type: ignore[no-untyped-def]
    return load_harness_settings(DEFAULT_CONFIG_DIR / "models.toml", ENV)


def test_harness_uses_the_repository_config_without_redis() -> None:
    loaded = settings()
    assert loaded.config_dir == DEFAULT_CONFIG_DIR
    assert loaded.models.prompts.judge == "v1"


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9380", "http://10.0.0.5:9380", "http://ragflow:9380"]
)
def test_ragflow_url_override_accepts_private_and_allow_listed_hosts(url: str) -> None:
    assert with_ragflow_url(settings(), url).models.ragflow.base_url == url


@pytest.mark.parametrize("url", ["http://8.8.8.8:9380", "not a url", "http://unresolvable.invalid"])
def test_ragflow_url_override_rejects_public_or_unknown_hosts(url: str) -> None:
    with pytest.raises(HarnessError):
        with_ragflow_url(settings(), url)


def test_config_errors_surface() -> None:
    from app.core.config import ConfigError

    with pytest.raises(ConfigError, match="MISTRAL_API_KEY"):
        load_harness_settings(Path(DEFAULT_CONFIG_DIR / "models.toml"), {})


def test_pipeline_record_marks_expected_citations_and_precision() -> None:
    item = EvalItem(
        id="x",
        question="q",
        type="factual",
        expected_source_ids=["https://example.org/a"],
        expected_answer_notes="n",
    )

    def cite(marker: int, url: str) -> Citation:
        return Citation(marker, f"c{marker}", f"s-{url}", url, "P", "T", None, None, "pdf", "e")

    answer = PipelineAnswer(
        outcome="answered",
        answer="A [1]. B [2]. C [3].",
        citations=[
            cite(1, "https://example.org/a"),
            cite(2, "https://example.org/a"),
            cite(3, "https://example.org/b"),
        ],
    )
    record = pipeline_record(item, answer)
    assert [c.expected for c in record.citations] == [True, True, False]
    assert record.citation_precision == 0.5  # two distinct sources, one expected
