"""P1b-15 b: the CI eval gate and accepting a new baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval import gate, results
from eval.cli import main
from eval.metrics import aggregate
from tests.factories import result
from tests.test_results_compare import run_data

REPO_RESULTS = Path(__file__).resolve().parents[1] / "results"


def run(run_id: str, *, regress: bool = False, mocked: bool = False) -> dict[str, Any]:
    data = run_data(mocked=mocked)
    data["meta"]["run_id"] = run_id
    if regress:  # every factual item misses retrieval: hit rates drop by 50 points
        items = [
            result("f1", hit10=False, hit5=False),
            result("f2", hit10=False, hit5=False, precision=0.0),
            result("o1", "out_of_corpus", outcome="answered", verdicts=("unsupported",)),
            result("o2", "out_of_corpus", outcome="abstained"),
        ]
        data = results.build(data["meta"], aggregate(items), items)
    return data


def commit(root: Path, data: dict[str, Any], *, redacted: bool = True) -> Path:
    folder = root / data["meta"]["run_id"]
    results.write(folder, gate.redact(data) if redacted else data)
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = commit(tmp_path, run("20261020T000000Z-base"))
    (tmp_path / gate.BASELINE_FILE).write_text(base.name + "\n", encoding="utf-8")
    return tmp_path


def test_a_regression_fails_the_gate(root: Path) -> None:
    commit(root, run("20261021T000000Z-new", regress=True))
    outcome = gate.gate(root)
    assert not outcome.ok
    assert set(outcome.regressions["20261021T000000Z-new"]) >= {"hit_at_5", "hit_at_10"}
    assert main(["gate", "--results-dir", str(root)]) == 1


def test_no_regression_passes_and_mocked_or_older_runs_are_not_candidates(root: Path) -> None:
    commit(root, run("20261021T000000Z-same"))
    commit(root, run("20261022T000000Z-mock", regress=True, mocked=True))
    commit(root, run("20261019T000000Z-old", regress=True))
    outcome = gate.gate(root)
    assert outcome.ok and outcome.checked == ["20261021T000000Z-same"]
    assert main(["gate", "--results-dir", str(root)]) == 0


def test_a_committed_answer_text_fails_the_gate(root: Path) -> None:
    commit(root, run("20261021T000000Z-raw"), redacted=False)
    outcome = gate.gate(root)
    assert outcome.unredacted == ["20261021T000000Z-raw"] and not outcome.ok


def test_redaction_keeps_metrics_and_removes_text() -> None:
    data = run("20261021T000000Z-x")
    data["items"][0]["pipeline"]["citations"][0]["excerpt"] = "Licensed passage."
    redacted = gate.redact(data)
    assert redacted["metrics"] == data["metrics"]
    text = json.dumps(redacted)
    assert "An answer." not in text and "Licensed passage." not in text
    assert gate.is_redacted(redacted) and not gate.is_redacted(data)


def test_accepting_a_baseline_redacts_records_and_refuses_a_silent_regression(
    root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("instance")
    worse = outside / "20261021T000000Z-worse"
    results.write(worse, run("20261021T000000Z-worse", regress=True))
    with pytest.raises(gate.GateError, match="regresses"):
        gate.accept_baseline(root, worse, reason="Synthetic")
    assert gate.baseline_name(root) == "20261020T000000Z-base"

    accepted = gate.accept_baseline(
        root, worse, reason="Owner decision: synthetic trade", accept_regression=True
    )
    assert accepted.previous == "20261020T000000Z-base"
    assert gate.baseline_name(root) == "20261021T000000Z-worse"
    copied = json.loads((root / "20261021T000000Z-worse" / "results.json").read_text())
    assert gate.is_redacted(copied)
    log = (root / gate.BASELINE_LOG).read_text()
    assert "regression accepted in" in log and "Owner decision: synthetic trade" in log
    assert gate.gate(root).ok  # the new baseline is the reference from now on

    with pytest.raises(gate.GateError, match="mocked"):
        mocked = outside / "20261022T000000Z-mock"
        results.write(mocked, run("20261022T000000Z-mock", mocked=True))
        gate.accept_baseline(root, mocked, reason="no")


def test_runs_reviewed_with_a_baseline_are_history(root: Path) -> None:
    commit(root, run("20261021T000000Z-experiment", regress=True))
    (root / gate.BASELINE_FILE).write_text(
        "20261020T000000Z-base\nreviewed-through 20261021T000000Z-experiment\n"
    )
    assert gate.gate(root).ok


def test_the_repository_gate_passes() -> None:
    # The committed baseline exists, every committed run is redacted, nothing regresses.
    outcome = gate.gate(REPO_RESULTS)
    assert outcome.ok, gate.gate_markdown(outcome, 3)
    assert outcome.baseline == "20261018T234701Z-a981e7bd8911"
