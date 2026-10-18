"""Map an eval set's file-name source references to canonical URLs (P0-17).

The research team writes ``expected_source_ids`` as corpus file names, which they
can see; the schema wants the canonical URL registered at ingestion. The corpus
manifest (``design/specs/corpus-manifest.md``) links the two: each row's file name
(the last part of ``path``) and its ``canonical_url``. Entries that already are a
URL or source UUID pass through. Nothing is guessed: a name the manifest does not
contain is a problem unless an explicit alias maps it to a manifest file name.

Several files can share one canonical URL (a publisher's landing page). An expected
URL then matches every one of them, which inflates hit@k and citation precision.
For those files the set should name the source register UUID instead, looked up by
file hash after ingestion (``register_ids``); such entries must be re-mapped if the
source is ingested again, since its UUID changes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from eval.schema import is_source_ref


@dataclass
class Mapped:
    lines: list[str] = field(default_factory=list)  # JSON lines of the mapped set
    problems: list[str] = field(default_factory=list)
    aliased: int = 0  # entries resolved through an alias
    shared_url: int = 0  # entries for a file whose canonical URL other files share
    by_uuid: dict[str, list[str]] = field(default_factory=dict)  # item id -> file names


def manifest_urls(manifest_text: str) -> dict[str, str]:
    """File name -> canonical URL for every file row of the manifest that has a URL."""
    urls: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(manifest_text, newline="")):
        path = (row.get("path") or "").strip()
        url = (row.get("canonical_url") or "").strip()
        if path and url:
            urls[PurePosixPath(path).name] = url
    return urls


def shared_url_paths(manifest_text: str) -> dict[str, str]:
    """File name -> manifest path, for files whose canonical URL another row also has."""
    rows = [
        ((row.get("path") or "").strip(), (row.get("canonical_url") or "").strip())
        for row in csv.DictReader(io.StringIO(manifest_text, newline=""))
    ]
    counts = Counter(url for _, url in rows if url)
    return {PurePosixPath(p).name: p for p, url in rows if p and url and counts[url] > 1}


def file_hashes(base: Path, paths: Mapping[str, str]) -> dict[str, str]:
    """File name -> sha256 of the file at ``base / path`` (what ingestion records)."""
    return {
        name: hashlib.sha256((base / path).read_bytes()).hexdigest() for name, path in paths.items()
    }


async def register_ids(database_url: str, hashes: Sequence[str]) -> dict[str, str]:
    """sha256 -> source register UUID for ingested sources (read-only query)."""
    from app.content.models import Source  # imports the API stack
    from app.core.db import create_engine, session_factory
    from sqlalchemy import select

    engine = create_engine(database_url)
    try:
        async with session_factory(engine)() as session:
            rows = await session.execute(
                select(Source.file_sha256, Source.id).where(
                    Source.file_sha256.in_(list(hashes)), Source.status == "ingested"
                )
            )
            found = {sha: str(source_id) for sha, source_id in rows if sha is not None}
            await session.rollback()
    finally:
        await engine.dispose()
    return found


def parse_aliases(pairs: Sequence[str]) -> dict[str, str]:
    """``old name=manifest file name`` pairs; split on the last ``=``."""
    aliases: dict[str, str] = {}
    for pair in pairs:
        old, sep, new = pair.rpartition("=")
        if not sep or not old.strip() or not new.strip():
            raise ValueError(f"alias must be 'name in the set=name in the manifest': {pair!r}")
        aliases[old.strip()] = new.strip()
    return aliases


def map_sources(
    set_text: str,
    urls: Mapping[str, str],
    aliases: Mapping[str, str] | None = None,
    *,
    shared: frozenset[str] = frozenset(),
    uuid_by_name: Mapping[str, str] | None = None,
) -> Mapped:
    """``shared`` names files whose URL is shared; with ``uuid_by_name`` they map to UUIDs."""
    aliases = aliases or {}
    out = Mapped()
    unused = set(aliases)
    for number, raw in enumerate(set_text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            out.problems.append(f"line {number}: not JSON: {exc.msg}")
            continue
        refs = item.get("expected_source_ids")
        if not isinstance(refs, list):
            out.problems.append(f"line {number}: expected_source_ids is not a list")
            continue
        mapped: list[str] = []
        for ref in refs:
            ref = str(ref).strip()
            if is_source_ref(ref):
                url = ref
            else:
                name = aliases.get(ref, ref)
                if name != ref:
                    unused.discard(ref)
                    out.aliased += 1
                if name not in urls:
                    out.problems.append(
                        f"line {number} ({item.get('id', '?')}): no manifest file named {ref!r}"
                    )
                    continue
                url = urls[name]
                if name in shared:
                    out.shared_url += 1
                    if uuid_by_name is not None:
                        if name not in uuid_by_name:
                            out.problems.append(
                                f"line {number} ({item.get('id', '?')}): {ref!r} shares its "
                                "canonical URL and has no ingested source in the register"
                            )
                            continue
                        url = uuid_by_name[name]
                        out.by_uuid.setdefault(str(item.get("id", "?")), []).append(name)
            if url not in mapped:  # two files may share one canonical URL
                mapped.append(url)
        item["expected_source_ids"] = mapped
        out.lines.append(json.dumps(item, ensure_ascii=False))
    out.problems += [f"alias not used: {old!r}" for old in sorted(unused)]
    return out
