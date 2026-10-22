"""The eval gate (P1b-15 b): committed results against the last accepted baseline.

Committed-results rule (owner decision, Oct 21, 2026; findings 1a §12): a run under
``results/`` may be committed only as ``summary.md`` and a ``results.json`` whose
answer and judged-statement text is redacted; metrics, counts, retrieval and judge
verdicts stay, which is all ``compare`` reads.

- ``results/BASELINE`` names the accepted baseline run (first line) and, on a line
  ``reviewed-through <run id>``, the newest run that was already committed when it was
  accepted: those were reviewed with that decision and are history, not candidates.
- ``python -m eval gate`` (CI, every push): every committed run must follow the rule,
  the baseline must exist and be a real (unmocked) run, and every unmocked run newer
  than the baseline and the reviewed-through run must not regress against it by more
  than the threshold (3 points). A regression fails the job.
- ``python -m eval accept-baseline <run folder> --reason "..."``: the documented way to
  accept a new baseline. It redacts the run into ``results/<run id>/``, compares it with
  the current baseline, refuses a regression unless ``--accept-regression`` is given
  (an owner decision, named in the reason), points ``BASELINE`` at it and appends the
  decision to ``results/BASELINE.md``. Commit the three together.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from eval import compare, results

BASELINE_FILE: Final = "BASELINE"
BASELINE_LOG: Final = "BASELINE.md"
ANSWER_REDACTED: Final = (
    "[redacted: answer text removed from the repository; metrics and judgements kept]"
)
STATEMENT_REDACTED: Final = "[redacted]"
GUARDRAILS_SUFFIX: Final = "-guardrails"  # synthetic guardrail runs, their own format


class GateError(RuntimeError):
    """The gate cannot run (no baseline, unreadable run); a failure, like a regression."""


@dataclass
class GateResult:
    baseline: str
    checked: list[str] = field(default_factory=list)
    regressions: dict[str, list[str]] = field(default_factory=dict)
    unredacted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.regressions and not self.unredacted


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """A copy with every answer and judged statement's text removed."""
    copy: dict[str, Any] = json.loads(json.dumps(data))
    for item in copy.get("items", []):
        pipeline = item.get("pipeline") or {}
        if pipeline.get("answer"):
            pipeline["answer"] = ANSWER_REDACTED
        for citation in pipeline.get("citations") or []:
            citation.pop("excerpt", None)
        for statement in (item.get("judge") or {}).get("statements") or []:
            statement["text"] = STATEMENT_REDACTED
    return copy


def is_redacted(data: dict[str, Any]) -> bool:
    """No answer or statement text, and no excerpt, anywhere in the items."""
    for item in data.get("items", []):
        pipeline = item.get("pipeline") or {}
        answer = str(pipeline.get("answer") or "")
        if answer and not answer.startswith("[redacted"):
            return False
        if any("excerpt" in c for c in pipeline.get("citations") or []):
            return False
        for statement in (item.get("judge") or {}).get("statements") or []:
            if not str(statement.get("text", "")).startswith("[redacted"):
                return False
    return True


def _runs(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir()
        and not p.name.endswith(GUARDRAILS_SUFFIX)
        and (p / results.RESULTS_JSON).exists()
    )


REVIEWED: Final = "reviewed-through "


def _baseline_lines(root: Path) -> tuple[str, str]:
    try:
        lines = (root / BASELINE_FILE).read_text(encoding="utf-8").split("\n")
    except FileNotFoundError:
        raise GateError(f"no {BASELINE_FILE} file under {root}") from None
    name = lines[0].strip()
    reviewed = next(
        (line[len(REVIEWED) :].strip() for line in lines[1:] if line.startswith(REVIEWED)), ""
    )
    if not name or "/" in name or not (root / name / results.RESULTS_JSON).exists():
        raise GateError(f"{BASELINE_FILE} names no committed run: {name!r}")
    return name, reviewed


def baseline_name(root: Path) -> str:
    return _baseline_lines(root)[0]


def gate(root: Path, threshold: float = compare.DEFAULT_THRESHOLD) -> GateResult:
    name, reviewed = _baseline_lines(root)
    base = results.load(root / name)
    if base["meta"]["mocked"]:
        raise GateError(f"the baseline {name} is a mocked run")
    outcome = GateResult(baseline=name)
    for run in _runs(root):
        data = json.loads((run / results.RESULTS_JSON).read_text(encoding="utf-8"))
        if not is_redacted(data):
            outcome.unredacted.append(run.name)
        # Run IDs start with a UTC timestamp, so names sort in time order.
        if run.name <= max(name, reviewed) or data["meta"]["mocked"]:
            continue
        outcome.checked.append(run.name)
        diff = compare.compare(base, data, threshold)
        if diff.regressions:
            outcome.regressions[run.name] = diff.regressions
    return outcome


def gate_markdown(outcome: GateResult, threshold: float) -> str:
    lines = [
        "# Eval gate",
        "",
        f"Baseline `{outcome.baseline}`; regression threshold {threshold:g} points.",
        "",
    ]
    for run in outcome.checked:
        found = outcome.regressions.get(run)
        lines.append(
            f"- `{run}`: " + ("REGRESSION in " + ", ".join(found) if found else "no regression")
        )
    if not outcome.checked:
        lines.append("- No run newer than the baseline is committed.")
    for run in outcome.unredacted:
        lines.append(f"- `{run}`: holds answer, statement or excerpt text (committed-results rule)")
    lines += ["", "**Pass.**" if outcome.ok else "**Fail.**", ""]
    return "\n".join(lines)


@dataclass(frozen=True)
class Acceptance:
    run_id: str
    previous: str | None
    comparison: compare.Comparison | None


def accept_baseline(
    root: Path,
    run_dir: Path,
    *,
    reason: str,
    accept_regression: bool = False,
    threshold: float = compare.DEFAULT_THRESHOLD,
    today: datetime | None = None,
) -> Acceptance:
    """Make ``run_dir`` (redacted into ``root``) the baseline; see the module."""
    if not reason.strip():
        raise GateError("a reason is required")
    data = results.load(run_dir)
    if data["meta"]["mocked"]:
        raise GateError("a mocked run cannot be the baseline")
    run_id = data["meta"]["run_id"]
    previous: str | None = None
    comparison: compare.Comparison | None = None
    if (root / BASELINE_FILE).exists():
        previous = baseline_name(root)
        comparison = compare.compare(results.load(root / previous), data, threshold)
        if comparison.regressions and not accept_regression:
            raise GateError(
                "the run regresses against the baseline in "
                + ", ".join(comparison.regressions)
                + "; pass --accept-regression only with the owner's decision in --reason"
            )
    target = root / run_id
    redacted = redact(data)
    if target.resolve() != run_dir.resolve():
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    (target / results.RESULTS_JSON).write_text(
        json.dumps(redacted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (target / results.SUMMARY_MD).write_text(results.summary_markdown(redacted), encoding="utf-8")
    newest = max((p.name for p in _runs(root)), default=run_id)
    (root / BASELINE_FILE).write_text(f"{run_id}\n{REVIEWED}{newest}\n", encoding="utf-8")
    when = (today or datetime.now(UTC)).date().isoformat()
    verdict = (
        "first baseline"
        if comparison is None
        else (
            "regression accepted in " + ", ".join(comparison.regressions)
            if comparison.regressions
            else "no regression"
        )
    )
    log = root / BASELINE_LOG
    if not log.exists():
        log.write_text(
            "# Accepted eval baselines\n\nNewest last. Written by "
            "`python -m eval accept-baseline`; the gate compares against the last one.\n\n"
            "| Date | Run | Previous | Verdict | Reason |\n| --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
    with log.open("a", encoding="utf-8") as fh:
        clean = " ".join(reason.split()).replace("|", "/")
        fh.write(f"| {when} | `{run_id}` | `{previous or '-'}` | {verdict} | {clean} |\n")
    return Acceptance(run_id, previous, comparison)
