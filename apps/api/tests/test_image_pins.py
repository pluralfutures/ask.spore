"""P1b-15 g: every container image the repository runs is pinned by digest as well as
by tag (infra/scripts/image-digests.py prints and writes the pins)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATTERNS = (
    "infra/**/docker-compose*.yml",
    "infra/compose*.yml",
    "apps/*/Dockerfile*",
    ".github/workflows/*.yml",
)
REF = re.compile(r"^\s*(?:image:\s*|FROM\s+)(\S+)", re.MULTILINE)
PINNED = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def test_every_image_is_pinned_by_tag_and_digest() -> None:
    refs = {
        (str(path.relative_to(ROOT)), ref)
        for pattern in PATTERNS
        for path in ROOT.glob(pattern)
        for ref in REF.findall(path.read_text(encoding="utf-8"))
    }
    assert len(refs) >= 15  # the scan found the Compose files, Dockerfiles and CI service
    unpinned = sorted(f"{path}: {ref}" for path, ref in refs if not PINNED.match(ref))
    assert unpinned == []
