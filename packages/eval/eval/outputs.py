"""Where a run's outputs go (P1c-12; the committed-results rule, owner decision of Oct 21,
2026).

A run writes its **full** outputs (answers, judged statements) under the runs directory,
outside the repository: ``--runs-dir``, else ``EVAL_RUNS_DIR``, else
``/srv/ask-spore/eval-runs/`` (root only on the Instance, where the Phase 1b release moved
the Oct 21 runs). Under ``results/`` it writes only the **redacted** copy
(``gate.redact``: metrics, counts, retrieval and judge verdicts, no answer, statement or
excerpt text), which may be committed and which the eval gate reads. So a working tree
with full outputs present still passes the gate: they are never under ``results/``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from eval import gate, results

DEFAULT_RUNS_DIR: Final = Path("/srv/ask-spore/eval-runs")
RUNS_DIR_ENV: Final = "EVAL_RUNS_DIR"


class OutputsError(RuntimeError):
    """The outputs cannot go where they were asked to (nothing was written)."""


def runs_dir(value: str | None, environ: Mapping[str, str] | None = None) -> Path:
    """The runs directory: the flag, else ``EVAL_RUNS_DIR``, else the default."""
    env = os.environ if environ is None else environ
    return Path(value or env.get(RUNS_DIR_ENV) or DEFAULT_RUNS_DIR)


def check_runs_dir(runs_root: Path, results_root: Path) -> None:
    """Refuse a runs directory inside ``results/`` (full outputs would sit where the
    committed, redacted runs are) and one that cannot be created or written."""
    runs, kept = runs_root.resolve(), results_root.resolve()
    if runs == kept or kept in runs.parents:
        raise OutputsError(
            f"the runs directory {runs_root} is inside {results_root}: full outputs never go "
            f"under results/ (pass --runs-dir or set {RUNS_DIR_ENV})"
        )
    try:
        runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputsError(
            f"cannot create the runs directory {runs_root} ({type(exc).__name__}); "
            f"pass --runs-dir or set {RUNS_DIR_ENV}"
        ) from None
    if not os.access(runs_root, os.W_OK):
        raise OutputsError(f"the runs directory {runs_root} is not writable")


def write_run(data: dict[str, Any], *, runs_root: Path, results_root: Path) -> tuple[Path, Path]:
    """Write the full run under ``runs_root`` and its redacted copy under ``results_root``;
    return both folders (full first)."""
    check_runs_dir(runs_root, results_root)
    run_id = str(data["meta"]["run_id"])
    full = runs_root / run_id
    results.write(full, data)
    redacted = results_root / run_id
    results.write(redacted, gate.redact(data))
    return full, redacted
