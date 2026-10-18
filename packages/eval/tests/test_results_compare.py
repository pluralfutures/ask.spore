"""P0-18: results folders, the Markdown summary, and ``compare``."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from eval import results
from eval.cli import main
from eval.compare import compare
from eval.metrics import aggregate
from tests.factories import result


def run_data(*, mocked: bool = True, threshold: float = 0.2) -> dict[str, Any]:
    items = [
        result("f1"),
        result("f2", hit10=False, hit5=False, precision=0.0),
        result("o1", "out_of_corpus", outcome="answered", verdicts=("unsupported",)),
        result("o2", "out_of_corpus", outcome="abstained"),
    ]
    meta = {
        "run_id": f"20261018T120000Z-abc123-{threshold}",
        "started_at": "2026-10-18T12:00:00+00:00",
        "duration_s": 1.0,
        "git_sha": "abc123",
        "git_dirty": False,
        "mocked": mocked,
        "synthetic_set": True,
        "notes": ["API run with tests.dev_fake_mistral"],
        "set": {"path": "s.jsonl", "sha256": "0" * 64, "items_run": 4, "items_in_set": 4},
        "config": {
            "chat_model": "mistral-large-2512",
            "rewrite_model": "mistral-small-2603",
            "judge_model": "mistral-large-2512",
            "prompts": ["corpus_only/v1", "rewrite/v1", "judge/v1"],
            "top_k": 10,
            "similarity_threshold": threshold,
            "max_context_tokens": 6000,
            "embedding_model": "BAAI/bge-m3@Builtin",
            "ragflow_version": "v0.27.2",
        },
        "corpus_version": "c0ffee",
        "package_datasets": 3,
        "warnings": ["1 answers came from the API's answer cache."],
    }
    return results.build(meta, aggregate(items), items)


def test_write_and_load_round_trip_with_labelled_summary(tmp_path: Path) -> None:
    data = run_data()
    folder = tmp_path / data["meta"]["run_id"]
    results.write(folder, data)
    assert results.load(folder)["metrics"] == data["metrics"]
    summary = (folder / results.SUMMARY_MD).read_text(encoding="utf-8")
    assert "**MOCKED RUN.**" in summary
    assert "**SYNTHETIC SET.**" in summary
    assert "| Retrieval hit@10 | 50.0 |" in summary
    assert "| o1 | out_of_corpus | answered | n/a | answered an out_of_corpus question |" in summary
    assert "| f2 | factual | answered | no | no expected source in the top 10 |" in summary
    assert "answer cache" in summary
    with pytest.raises(FileExistsError):
        results.write(folder, data)  # never overwrite a run


def test_unmocked_summary_has_no_mocked_banner() -> None:
    assert "MOCKED" not in results.summary_markdown(run_data(mocked=False))


def test_compare_flags_drops_beyond_the_threshold_only() -> None:
    base = run_data()
    new = copy.deepcopy(base)
    new["metrics"]["hit_at_5"] = base["metrics"]["hit_at_5"] - 3.0  # exactly the threshold
    new["metrics"]["faithfulness"] = base["metrics"]["faithfulness"] - 3.1
    new["metrics"]["abstention_correctness"] = 100.0  # improvement
    new["metrics"]["citation_precision"] = None
    outcome = compare(base, new, threshold=3.0)
    assert outcome.regressions == ["faithfulness"]
    assert any("citation_precision" in n for n in outcome.notes)
    assert any("mocked" in n for n in outcome.notes)


def test_compare_notes_configuration_and_set_changes() -> None:
    base, new = run_data(threshold=0.2), run_data(threshold=0.3)
    new["meta"]["set"]["sha256"] = "1" * 64
    notes = compare(base, new, 3.0).notes
    assert "Configuration differs in: similarity_threshold." in notes
    assert "The eval sets differ; metrics are not strictly comparable." in notes


def test_compare_command_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, new = run_data(threshold=0.2), run_data(threshold=0.3)
    new["metrics"]["hit_at_10"] = 10.0
    results.write(tmp_path / "base", base)
    results.write(tmp_path / "new", new)
    out_file = tmp_path / "diff.md"
    assert main(["compare", str(tmp_path / "base"), str(tmp_path / "new")]) == 1
    assert "REGRESSION" in capsys.readouterr().out
    assert (
        main(
            [
                "compare",
                str(tmp_path / "base"),
                str(tmp_path / "new"),
                "--threshold",
                "50",
                "--output",
                str(out_file),
            ]
        )
        == 0
    )
    assert "No regression." in out_file.read_text(encoding="utf-8")
    assert main(["compare", str(tmp_path / "base"), str(tmp_path / "base")]) == 0
