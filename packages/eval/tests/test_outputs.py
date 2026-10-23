"""P1c-12: full run outputs go to the runs directory, outside the repository; only the
redacted copy goes under results/, so the gate passes with full outputs present."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from eval import gate, outputs, results
from eval.cli import main
from tests.test_gate import REPO_RESULTS, run


def test_the_runs_directory_comes_from_the_flag_the_environment_or_the_default() -> None:
    assert outputs.runs_dir(None, {}) == Path("/srv/ask-spore/eval-runs")
    assert outputs.runs_dir(None, {"EVAL_RUNS_DIR": "/var/eval/runs"}) == Path("/var/eval/runs")
    assert outputs.runs_dir("/x/runs", {"EVAL_RUNS_DIR": "/var/eval/runs"}) == Path("/x/runs")


def test_a_run_writes_full_outputs_outside_and_a_redacted_copy_under_results(
    tmp_path: Path,
) -> None:
    results_root, runs_root = tmp_path / "repo" / "results", tmp_path / "srv" / "eval-runs"
    data = run("20261024T000000Z-abc")
    answer = data["items"][0]["pipeline"]["answer"]
    assert answer and not answer.startswith("[redacted")

    full, redacted = outputs.write_run(data, runs_root=runs_root, results_root=results_root)

    assert (full, redacted) == (runs_root / data["meta"]["run_id"], results_root / full.name)
    assert results.load(full)["items"][0]["pipeline"]["answer"] == answer
    kept = results.load(redacted)
    assert gate.is_redacted(kept)
    assert answer not in (redacted / results.RESULTS_JSON).read_text(encoding="utf-8")
    assert answer not in (redacted / results.SUMMARY_MD).read_text(encoding="utf-8")
    assert (kept["metrics"], kept["counts"]) == (data["metrics"], data["counts"])
    assert runs_root.stat().st_mode & 0o077 == 0  # root only on the Instance


def test_full_outputs_never_go_under_results(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    for inside in (results_root, results_root / "full"):
        with pytest.raises(outputs.OutputsError, match="inside"):
            outputs.write_run(
                run("20261024T000000Z-abc"), runs_root=inside, results_root=results_root
            )
    assert not results_root.exists()


def test_the_cli_refuses_a_runs_directory_under_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EVAL_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVAL_USER_EMAIL", "eval-service@example.org")
    results_root = tmp_path / "results"
    code = main(
        [
            "run",
            "--results-dir",
            str(results_root),
            "--runs-dir",
            str(results_root / "full"),
        ]
    )
    assert code == 2
    assert "never go under results/" in capsys.readouterr().err


def test_the_gate_passes_on_a_tree_with_full_outputs_present(tmp_path: Path) -> None:
    """The repository's results/ plus a new run: its full outputs sit beside the tree (as
    on the Instance), its redacted copy under results/; the gate reads results/ only."""
    results_root = tmp_path / "packages" / "eval" / "results"
    shutil.copytree(REPO_RESULTS, results_root)
    runs_root = tmp_path / "srv" / "eval-runs"
    data = run("20991231T000000Z-newest")
    data["meta"]["mocked"] = False
    baseline = results.load(results_root / gate.baseline_name(results_root))
    # Same figures as the baseline: a run that does not regress.
    data["metrics"] = json.loads(json.dumps(baseline["metrics"]))
    full, _ = outputs.write_run(data, runs_root=runs_root, results_root=results_root)

    assert not gate.is_redacted(results.load(full))  # full text is present, outside
    outcome = gate.gate(results_root)
    assert outcome.ok, gate.gate_markdown(outcome, 3)
    assert "20991231T000000Z-newest" in outcome.checked
    # Negative control: the same full folder under results/ fails the gate.
    shutil.copytree(full, results_root / "20991231T000001Z-leaked")
    assert gate.gate(results_root).unredacted == ["20991231T000001Z-leaked"]
