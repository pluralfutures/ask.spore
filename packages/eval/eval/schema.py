"""Eval set schema (P0-17): one JSON object per line of a ``.jsonl`` file.

``EvalItem`` is the single source of truth. ``schema/eval-item.schema.json`` is
generated from it (``python -m eval schema``) for editors and other tools, and a
test keeps the two in step. Field meanings and authoring rules are in
``packages/eval/README.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from app.api.schemas import MAX_QUESTION_CHARS
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ItemType = Literal["factual", "synthesis", "out_of_corpus"]
ITEM_TYPES: tuple[ItemType, ...] = ("factual", "synthesis", "out_of_corpus")

MAX_NOTES_CHARS = 4000
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
LABEL_PATTERN = r"^[a-z0-9][a-z0-9:._-]{0,63}$"

# Defaults of `validate` match the spec for eval set v1 (P0-17).
V1_MIN_ITEMS = 60
V1_MIN_OUT_OF_CORPUS = 10


def is_source_ref(value: str) -> bool:
    """A source register UUID, or the source's ``canonical_url`` (http or https)."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        pass
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and value == value.strip()


class EvalItem(BaseModel):
    """One eval question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(
        pattern=ID_PATTERN,
        description="Stable, unique within the set; never reused for a different question.",
    )
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        description="Asked exactly as written, as the first turn of a new conversation.",
    )
    type: ItemType = Field(
        description="factual: one fact from one source; synthesis: combines several "
        "statements, usually across sources; out_of_corpus: the corpus cannot answer it."
    )
    expected_source_ids: list[str] = Field(
        description="Sources that answer the question: source register UUIDs or the "
        "sources' canonical URLs. At least one for factual and synthesis; empty for "
        "out_of_corpus.",
    )
    expected_answer_notes: str = Field(
        min_length=1,
        max_length=MAX_NOTES_CHARS,
        description="What a correct answer says, for human review of results. For "
        "out_of_corpus: why the corpus cannot answer.",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Optional free grouping, e.g. 'table', 'pptx', 'lang:de'.",
    )
    synthetic: bool = Field(
        default=False,
        description="True for invented items written against the synthetic corpus.",
    )

    @field_validator("question", "expected_answer_notes")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("expected_source_ids")
    @classmethod
    def _source_refs(cls, value: list[str]) -> list[str]:
        bad = [ref for ref in value if not is_source_ref(ref)]
        if bad:
            raise ValueError(f"not a source UUID or http(s) canonical URL: {bad}")
        if len(set(value)) != len(value):
            raise ValueError("duplicate entries")
        return value

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: list[str]) -> list[str]:
        bad = [label for label in value if not re.fullmatch(LABEL_PATTERN, label)]
        if bad:
            raise ValueError(f"labels must match {LABEL_PATTERN}: {bad}")
        return value

    @model_validator(mode="after")
    def _sources_match_type(self) -> EvalItem:
        if self.type == "out_of_corpus" and self.expected_source_ids:
            raise ValueError("out_of_corpus items must have empty expected_source_ids")
        if self.type != "out_of_corpus" and not self.expected_source_ids:
            raise ValueError(f"{self.type} items need at least one expected_source_ids entry")
        return self


def json_schema() -> dict[str, Any]:
    schema = EvalItem.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "ask.spore eval item"
    return schema


@dataclass
class ValidationReport:
    path: Path
    items: list[EvalItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def counts(self) -> dict[str, int]:
        found = Counter(item.type for item in self.items)
        return {name: found.get(name, 0) for name in ITEM_TYPES}

    def check_minimums(self, min_items: int, min_out_of_corpus: int) -> None:
        if len(self.items) < min_items:
            self.errors.append(f"{len(self.items)} items; at least {min_items} required")
        ooc = self.counts()["out_of_corpus"]
        if ooc < min_out_of_corpus:
            self.errors.append(f"{ooc} out_of_corpus items; at least {min_out_of_corpus} required")


def _describe(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "item"
        parts.append(f"{where}: {err['msg']}")
    return "; ".join(parts)


def load_set(path: Path) -> ValidationReport:
    """Parse and validate every line; collect all problems rather than stop at the first."""
    report = ValidationReport(path=path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        report.errors.append(f"{path}: file not found")
        return report
    except UnicodeDecodeError:
        report.errors.append(f"{path}: not UTF-8")
        return report
    seen: dict[str, int] = {}
    questions: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            report.errors.append(f"line {number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(raw, dict):
            report.errors.append(f"line {number}: must be a JSON object")
            continue
        try:
            item = EvalItem.model_validate(raw)
        except ValidationError as exc:
            report.errors.append(f"line {number}: {_describe(exc)}")
            continue
        if item.id in seen:
            report.errors.append(
                f"line {number}: duplicate id '{item.id}' (first on line {seen[item.id]})"
            )
            continue
        key = " ".join(item.question.casefold().split())
        if key in questions:
            report.errors.append(f"line {number}: same question as line {questions[key]}")
            continue
        seen[item.id] = number
        questions[key] = number
        report.items.append(item)
    if not report.items and not report.errors:
        report.errors.append(f"{path}: no items")
    return report


def set_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
