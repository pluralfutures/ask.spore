"""``python -m eval``: validate eval sets, map their sources, run the harness, compare results."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from app.core.config import ConfigError

from eval import compare, results, sources
from eval.schema import V1_MIN_ITEMS, V1_MIN_OUT_OF_CORPUS, json_schema, load_set

PACKAGE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_FILE = PACKAGE_DIR / "schema" / "eval-item.schema.json"
DEFAULT_CONFIG = PACKAGE_DIR.parents[1] / "config" / "models.toml"
DEFAULT_SET = PACKAGE_DIR / "sets" / "v1.jsonl"
DEFAULT_RESULTS = PACKAGE_DIR / "results"


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def cmd_validate(args: argparse.Namespace) -> int:
    report = load_set(Path(args.file))
    if report.items:
        report.check_minimums(args.min_items, args.min_out_of_corpus)
    counts = report.counts()
    summary = ", ".join(f"{n} {name}" for name, n in counts.items())
    synthetic = sum(item.synthetic for item in report.items)
    for error in report.errors:
        _err(f"{args.file}: {error}")
    status = "ok" if report.ok else "INVALID"
    _out(
        f"{args.file}: {status}: {len(report.items)} valid items ({summary}); {synthetic} synthetic"
    )
    return 0 if report.ok else 1


def cmd_map_sources(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest)
    try:
        aliases = sources.parse_aliases(args.alias)
        set_text = Path(args.file).read_text(encoding="utf-8")
        manifest_text = manifest.read_text(encoding="utf-8-sig")
        urls = sources.manifest_urls(manifest_text)
        shared = sources.shared_url_paths(manifest_text)
        uuid_by_name: dict[str, str] | None = None
        if args.uuid_for_shared_urls:
            database_url = os.environ.get("DATABASE_URL", "")
            if not database_url:
                raise ValueError("--uuid-for-shared-urls needs DATABASE_URL")
            hashes = sources.file_hashes(manifest.parent, shared)
            ids = asyncio.run(sources.register_ids(database_url, sorted(set(hashes.values()))))
            uuid_by_name = {name: ids[sha] for name, sha in hashes.items() if sha in ids}
    except (OSError, ValueError) as exc:
        _err(f"python -m eval map-sources: {exc}")
        return 2
    mapped = sources.map_sources(
        set_text, urls, aliases, shared=frozenset(shared), uuid_by_name=uuid_by_name
    )
    for problem in mapped.problems:
        _err(f"{args.file}: {problem}")
    if mapped.problems:
        _out(f"{args.file}: not written: {len(mapped.problems)} problem(s)")
        return 1
    Path(args.output).write_text("\n".join(mapped.lines) + "\n", encoding="utf-8")
    _out(f"wrote {args.output}: {len(mapped.lines)} items, {mapped.aliased} entries via aliases")
    if uuid_by_name is not None:
        _out(f"register UUIDs for shared-URL files in {len(mapped.by_uuid)} items:")
        for item_id, names in mapped.by_uuid.items():
            _out(f"  {item_id}: {len(names)} entr{'y' if len(names) == 1 else 'ies'}")
    elif mapped.shared_url:
        _out(
            f"warning: {mapped.shared_url} entries name files whose canonical URL other files "
            "share; any of them counts as a hit (use --uuid-for-shared-urls after ingestion)"
        )
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if args.write:
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_FILE.write_text(text, encoding="utf-8")
        _out(f"wrote {SCHEMA_FILE}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from eval.runner import HarnessError, RunOptions, run  # imports the API stack

    api_url = args.api_url or os.environ.get("EVAL_API_URL", "")
    user_email = os.environ.get("EVAL_USER_EMAIL", "")
    missing = [
        n
        for n, v in (("--api-url or EVAL_API_URL", api_url), ("EVAL_USER_EMAIL", user_email))
        if not v
    ]
    if missing:
        _err("python -m eval run: missing " + ", ".join(missing))
        return 2
    options = RunOptions(
        config=Path(args.config),
        set_path=Path(args.set),
        api_url=api_url,
        user_email=user_email,
        results_root=Path(args.results_dir),
        ragflow_url=args.ragflow_url or os.environ.get("EVAL_RAGFLOW_URL") or None,
        mock_mistral=args.mock_mistral,
        notes=list(args.note),
        limit=args.limit,
    )
    try:
        directory = asyncio.run(run(options))
    except (HarnessError, ConfigError) as exc:
        _err(f"python -m eval run: {exc}")
        return 2
    data = results.load(directory)
    _out(results.summary_markdown(data))
    _out(f"results: {directory}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"results_dir={directory}\n")
    counts = data["counts"]
    return 1 if counts["pipeline_errors"] or counts["retrieval_errors"] else 0


def cmd_compare(args: argparse.Namespace) -> int:
    base, new = results.load(Path(args.base)), results.load(Path(args.new))
    outcome = compare.compare(base, new, args.threshold)
    text = compare.markdown(outcome, base["meta"]["run_id"], new["meta"]["run_id"], args.threshold)
    _out(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 1 if outcome.regressions else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate",
        help="check an eval set against the schema",
        description="Checks every line and reports all problems. The minimums default to "
        f"the spec for eval set v1 ({V1_MIN_ITEMS} items, {V1_MIN_OUT_OF_CORPUS} "
        "out_of_corpus); lower them for smaller sets.",
    )
    validate.add_argument("file", help="path to a .jsonl eval set")
    validate.add_argument("--min-items", type=int, default=V1_MIN_ITEMS)
    validate.add_argument("--min-out-of-corpus", type=int, default=V1_MIN_OUT_OF_CORPUS)
    validate.set_defaults(func=cmd_validate)

    map_cmd = commands.add_parser(
        "map-sources",
        help="replace file names in expected_source_ids with canonical URLs from a manifest",
        description="Reads a .jsonl set whose expected_source_ids are corpus file names and "
        "the corpus manifest.csv, and writes the set with each file's canonical_url. Writes "
        "nothing if any name is not in the manifest; map it with --alias.",
    )
    map_cmd.add_argument("file", help="eval set with file names (.jsonl)")
    map_cmd.add_argument("--manifest", required=True, help="corpus manifest.csv")
    map_cmd.add_argument("--output", "-o", required=True, help="where to write the mapped set")
    map_cmd.add_argument(
        "--alias",
        action="append",
        default=[],
        help="'name in the set=file name in the manifest'; repeatable",
    )
    map_cmd.add_argument(
        "--uuid-for-shared-urls",
        action="store_true",
        help="after ingestion: for files whose canonical URL other files share, use the "
        "source register UUID (looked up by file hash; needs DATABASE_URL, read-only)",
    )
    map_cmd.set_defaults(func=cmd_map_sources)
    schema = commands.add_parser("schema", help="print the JSON Schema of one eval item")
    schema.add_argument("--write", action="store_true", help=f"write it to {SCHEMA_FILE.name}")
    schema.set_defaults(func=cmd_schema)

    run_cmd = commands.add_parser(
        "run",
        help="run an eval set through the retrieval step, the API and the judge",
        description="Needs MISTRAL_API_KEY, RAGFLOW_API_KEY, DATABASE_URL, "
        "PHASE0_BEARER_TOKEN and EVAL_USER_EMAIL in the environment (see eval/runner.py). "
        "Writes results/<timestamp>-<git-sha>/. Exits 1 if any item errored.",
    )
    run_cmd.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to models.toml")
    run_cmd.add_argument("--set", default=str(DEFAULT_SET), help="eval set (.jsonl)")
    run_cmd.add_argument("--api-url", help="API under test (default: EVAL_API_URL)")
    run_cmd.add_argument(
        "--ragflow-url",
        help="RAGFlow base URL for the retrieval step if ragflow.base_url is not reachable "
        "from here (default: EVAL_RAGFLOW_URL); must be a private or loopback address",
    )
    run_cmd.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    run_cmd.add_argument("--limit", type=int, help="run only the first N items")
    run_cmd.add_argument(
        "--note", action="append", default=[], help="line for the summary; repeatable"
    )
    run_cmd.add_argument(
        "--mock-mistral",
        action="store_true",
        help="DEV ONLY: lexical stand-in for the judge (eval/mock.py); the run is labelled mocked",
    )
    run_cmd.set_defaults(func=cmd_run)

    compare_cmd = commands.add_parser(
        "compare",
        help="diff two results folders",
        description="Exits 1 when any headline metric drops by more than the threshold.",
    )
    compare_cmd.add_argument("base", help="baseline results folder")
    compare_cmd.add_argument("new", help="results folder to check")
    compare_cmd.add_argument(
        "--threshold",
        type=float,
        default=compare.DEFAULT_THRESHOLD,
        help=f"points (default {compare.DEFAULT_THRESHOLD:g})",
    )
    compare_cmd.add_argument("--output", help="also write the Markdown diff to this file")
    compare_cmd.set_defaults(func=cmd_compare)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code
