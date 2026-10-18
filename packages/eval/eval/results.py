"""Results folders: ``results/<timestamp>-<git-sha>/results.json`` and ``summary.md``."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from eval.metrics import HEADLINE
from eval.records import ItemResult

RESULTS_JSON = "results.json"
SUMMARY_MD = "summary.md"
FORMAT_VERSION = 1

LABELS = {
    "hit_at_5": "Retrieval hit@5",
    "hit_at_10": "Retrieval hit@10",
    "citation_precision": "Citation precision",
    "faithfulness": "Faithfulness",
    "abstention_correctness": "Abstention correctness (out_of_corpus)",
    "in_corpus_answer_rate": "Cited-answer rate (factual + synthesis)",
}


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def build(meta: dict[str, Any], summary: dict[str, Any], items: list[ItemResult]) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "meta": meta,
        **summary,
        "items": [asdict(item) for item in items],
    }


def summary_markdown(data: dict[str, Any]) -> str:
    meta, metrics, diag, counts = data["meta"], data["metrics"], data["diagnostics"], data["counts"]
    config = meta["config"]
    lines = [f"# Eval run {meta['run_id']}", ""]
    if meta["mocked"]:
        lines += [
            "> **MOCKED RUN.** Mistral was mocked; faithfulness comes from a lexical stand-in, "
            "not a model. These numbers prove the harness, not answer quality.",
            "",
        ]
    if meta["synthetic_set"]:
        lines += [
            "> **SYNTHETIC SET.** Every item is synthetic, written against the synthetic "
            "corpus. Results say nothing about the real corpus.",
            "",
        ]
    lines += [f"- {note}" for note in meta["notes"]]
    if meta["notes"]:
        lines.append("")
    lines += [
        "| Metric | Points |",
        "| --- | ---: |",
        *(f"| {LABELS[name]} | {fmt(metrics[name])} |" for name in HEADLINE),
        "",
        "## Run",
        "",
        f"- Set: `{meta['set']['path']}` ({counts['items']} items: {counts['factual']} factual, "
        f"{counts['synthesis']} synthesis, {counts['out_of_corpus']} out_of_corpus), "
        f"sha256 `{meta['set']['sha256'][:12]}`",
        f"- Code: `{meta['git_sha']}`{' (uncommitted changes)' if meta['git_dirty'] else ''}; "
        f"started {meta['started_at']}, {meta['duration_s']} s",
        f"- Retrieval: top_k {config['top_k']}, similarity threshold "
        f"{config['similarity_threshold']}, max context tokens {config['max_context_tokens']}, "
        f"embedding `{config['embedding_model']}`, RAGFlow {config['ragflow_version']}",
        f"- Models: answer `{config['chat_model']}`, rewrite `{config['rewrite_model']}`, "
        f"judge `{config['judge_model']}`; prompts {', '.join(config['prompts'])}",
        f"- Corpus version `{meta['corpus_version']}`, {meta['package_datasets']} datasets",
        "",
        "## Outcomes",
        "",
        f"- Answered {counts['answered']}, unsupported {counts['unsupported']}, "
        f"abstained {counts['abstained']}, errors {counts['pipeline_errors']}",
        f"- out_of_corpus abstained without an LLM call: "
        f"{fmt(diag['out_of_corpus_abstained_without_llm'])} points",
        f"- Retrieval step would abstain: out_of_corpus "
        f"{fmt(diag['out_of_corpus_retrieval_would_abstain'])}, factual + synthesis "
        f"{fmt(diag['in_corpus_retrieval_would_abstain'])} points",
        f"- Judged statements: {diag['statements_supported']} supported, "
        f"{diag['statements_unsupported']} unsupported, {diag['statements_no_claim']} no claim; "
        f"judge errors {counts['judge_errors']}, excerpt fallbacks {counts['excerpt_fallbacks']}",
        f"- Tokens: pipeline {counts['pipeline_tokens_in']} in / {counts['pipeline_tokens_out']} "
        f"out; judge {counts['judge_tokens_in']} in / {counts['judge_tokens_out']} out",
        "",
    ]
    if meta["warnings"]:
        lines += ["## Warnings", "", *(f"- {w}" for w in meta["warnings"]), ""]
    misses = [
        i
        for i in data["items"]
        if (i["type"] == "out_of_corpus" and i["pipeline"]["outcome"] == "answered")
        or (i["type"] != "out_of_corpus" and i["retrieval"]["hit_at_10"] is False)
        or i["pipeline"]["outcome"] == "error"
    ]
    if misses:
        lines += ["## Items to look at", "", "| Item | Type | Outcome | hit@10 | Note |"]
        lines.append("| --- | --- | --- | --- | --- |")
        for i in misses:
            note = (
                i["pipeline"]["error_code"]
                or ("answered an out_of_corpus question" if i["type"] == "out_of_corpus" else "")
                or "no expected source in the top 10"
            )
            hit = i["retrieval"]["hit_at_10"]
            lines.append(
                f"| {i['id']} | {i['type']} | {i['pipeline']['outcome']} | "
                f"{'n/a' if hit is None else ('yes' if hit else 'no')} | {note} |"
            )
        lines.append("")
    return "\n".join(lines)


def write(directory: Path, data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / RESULTS_JSON).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (directory / SUMMARY_MD).write_text(summary_markdown(data), encoding="utf-8")


def load(directory: Path) -> dict[str, Any]:
    path = directory / RESULTS_JSON
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported format_version {data.get('format_version')}")
    return data
