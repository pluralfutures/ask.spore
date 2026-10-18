"""``python -m eval``: validate eval sets, run the harness, compare results."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from eval.schema import V1_MIN_ITEMS, V1_MIN_OUT_OF_CORPUS, json_schema, load_set

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schema" / "eval-item.schema.json"


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


def cmd_schema(args: argparse.Namespace) -> int:
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if args.write:
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_FILE.write_text(text, encoding="utf-8")
        _out(f"wrote {SCHEMA_FILE}")
    else:
        sys.stdout.write(text)
    return 0


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

    schema = commands.add_parser("schema", help="print the JSON Schema of one eval item")
    schema.add_argument("--write", action="store_true", help=f"write it to {SCHEMA_FILE.name}")
    schema.set_defaults(func=cmd_schema)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code
