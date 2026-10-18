"""Eval set schema and validator (P0-17)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval.cli import SCHEMA_FILE, main
from eval.schema import json_schema, load_set

SETS = Path(__file__).resolve().parents[1] / "sets"


def item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t-001",
        "question": "What was installed capacity in 2025?",
        "type": "factual",
        "expected_source_ids": ["https://example.org/report"],
        "expected_answer_notes": "4.2 GW",
    }
    base.update(overrides)
    return base


def write(tmp_path: Path, *rows: dict[str, Any] | str) -> Path:
    path = tmp_path / "set.jsonl"
    lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_items_load(tmp_path: Path) -> None:
    report = load_set(
        write(
            tmp_path,
            item(),
            item(
                id="t-002",
                question="Compare A and B",
                type="synthesis",
                expected_source_ids=[
                    "https://example.org/a",
                    "3f2b8c1e-7d4a-4c2b-9e1f-0a1b2c3d4e5f",
                ],
            ),
            "",
            item(id="t-003", question="Who won?", type="out_of_corpus", expected_source_ids=[]),
        )
    )
    assert report.ok, report.errors
    assert report.counts() == {"factual": 1, "synthesis": 1, "out_of_corpus": 1}


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (item(type="opinion"), "type"),
        (item(expected_source_ids=[]), "at least one"),
        (item(type="out_of_corpus"), "must have empty"),
        (item(expected_source_ids=["report.pdf"]), "not a source UUID"),
        (item(expected_source_ids=["ftp://example.org/x"]), "not a source UUID"),
        (
            item(expected_source_ids=["https://example.org/a", "https://example.org/a"]),
            "duplicate",
        ),
        (item(question="   "), "blank"),
        (item(expected_answer_notes=""), "expected_answer_notes"),
        (item(id="has space"), "id"),
        (item(labels=["Has Caps"]), "labels"),
        (item(extra_field=1), "extra_field"),
        ({k: v for k, v in item().items() if k != "question"}, "question"),
        (item(question="x" * 4001), "question"),
    ],
)
def test_invalid_item_reported_with_line(tmp_path: Path, row: dict[str, Any], message: str) -> None:
    report = load_set(write(tmp_path, item(id="ok-1", question="fine"), row))
    assert not report.ok
    assert len(report.errors) == 1
    assert report.errors[0].startswith("line 2:")
    assert message in report.errors[0]


def test_every_problem_is_reported(tmp_path: Path) -> None:
    report = load_set(write(tmp_path, "{not json", "[1, 2]", item(type="x"), item(), item()))
    assert [e.split(":")[0] for e in report.errors] == ["line 1", "line 2", "line 3", "line 5"]
    assert "duplicate id 't-001'" in report.errors[-1]


def test_duplicate_question_ignores_case_and_spacing(tmp_path: Path) -> None:
    again = item(id="t-002", question=" what was  INSTALLED capacity in 2025?")
    report = load_set(write(tmp_path, item(), again))
    assert report.errors == ["line 2: same question as line 1"]


def test_minimums(tmp_path: Path) -> None:
    report = load_set(write(tmp_path, item()))
    report.check_minimums(min_items=2, min_out_of_corpus=1)
    assert report.errors == [
        "1 items; at least 2 required",
        "0 out_of_corpus items; at least 1 required",
    ]


def test_missing_and_empty_files(tmp_path: Path) -> None:
    assert "file not found" in load_set(tmp_path / "nope.jsonl").errors[0]
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert "no items" in load_set(empty).errors[0]


def test_validate_command_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, item())
    assert main(["validate", str(path)]) == 1  # v1 minimums by default
    assert main(["validate", str(path), "--min-items", "1", "--min-out-of-corpus", "0"]) == 0
    out = capsys.readouterr().out
    assert "ok: 1 valid items (1 factual, 0 synthesis, 0 out_of_corpus)" in out


def test_committed_json_schema_matches_model() -> None:
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == json_schema()


def test_template_is_valid() -> None:
    report = load_set(SETS / "template.jsonl")
    assert report.ok, report.errors
    assert set(report.counts().values()) == {1}


def test_synthetic_set_meets_its_minimums_and_is_marked() -> None:
    report = load_set(SETS / "synthetic-v0.jsonl")
    report.check_minimums(min_items=30, min_out_of_corpus=6)
    assert report.ok, report.errors
    assert all(i.synthetic for i in report.items)
    assert all(i.id.startswith("syn-") for i in report.items)
    assert all(
        ref.startswith("https://example.org/synthetic/")
        for i in report.items
        for ref in i.expected_source_ids
    )
