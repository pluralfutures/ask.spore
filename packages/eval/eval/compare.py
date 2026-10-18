"""``compare``: diff two results folders; a drop beyond the threshold is a regression."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.metrics import HEADLINE
from eval.results import LABELS, fmt

DEFAULT_THRESHOLD = 3.0  # points


@dataclass(frozen=True)
class Row:
    metric: str
    base: float | None
    new: float | None

    @property
    def delta(self) -> float | None:
        if self.base is None or self.new is None:
            return None
        return round(self.new - self.base, 1)


@dataclass(frozen=True)
class Comparison:
    rows: list[Row]
    regressions: list[str]
    notes: list[str]


def compare(base: dict[str, Any], new: dict[str, Any], threshold: float) -> Comparison:
    rows = [Row(m, base["metrics"].get(m), new["metrics"].get(m)) for m in HEADLINE]
    regressions = [
        r.metric for r in rows if r.delta is not None and r.delta < 0 and -r.delta > threshold
    ]
    notes: list[str] = []
    if base["meta"]["set"]["sha256"] != new["meta"]["set"]["sha256"]:
        notes.append("The eval sets differ; metrics are not strictly comparable.")
    for flag, text in (("mocked", "mocked"), ("synthetic_set", "on the synthetic set")):
        if base["meta"][flag] or new["meta"][flag]:
            notes.append(f"At least one run is {text}.")
    changed = sorted(
        k
        for k in set(base["meta"]["config"]) | set(new["meta"]["config"])
        if base["meta"]["config"].get(k) != new["meta"]["config"].get(k)
    )
    if changed:
        notes.append("Configuration differs in: " + ", ".join(changed) + ".")
    if base["meta"]["corpus_version"] != new["meta"]["corpus_version"]:
        notes.append("The corpus version differs.")
    skipped = [r.metric for r in rows if r.delta is None]
    if skipped:
        notes.append("Not compared (n/a in a run): " + ", ".join(skipped) + ".")
    return Comparison(rows, regressions, notes)


def markdown(result: Comparison, base_id: str, new_id: str, threshold: float) -> str:
    lines = [
        f"# Compare {base_id} -> {new_id}",
        "",
        f"Regression threshold: a drop of more than {threshold:g} points.",
        "",
        "| Metric | Base | New | Change | |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in result.rows:
        delta = "n/a" if row.delta is None else f"{row.delta:+.1f}"
        flag = "REGRESSION" if row.metric in result.regressions else ""
        lines.append(
            f"| {LABELS[row.metric]} | {fmt(row.base)} | {fmt(row.new)} | {delta} | {flag} |"
        )
    lines.append("")
    lines += [f"- {note}" for note in result.notes]
    verdict = (
        f"**{len(result.regressions)} regression(s).**" if result.regressions else "No regression."
    )
    lines += ["", verdict, ""]
    return "\n".join(lines)
