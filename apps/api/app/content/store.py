"""Our own copies of ingested files, for downloads (P1a-14).

RAGFlow is internal and its endpoints are never exposed through our API (CLAUDE.md),
so downloads cannot be served from it. At ingestion, a PDF, DOCX or PPTX file is
written under ``[files] content_root`` as ``<first two hex digits>/<sha256>.<type>``:
named by its content hash, never by the original file name, so neither the path nor a
log line carries a client document's name. ``sources.stored_path`` records the relative
path (a check constraint ties it to ``file_sha256``). Reading checks that the path stays
under the root and that the bytes still hash to ``file_sha256``.

Pages (HTML, Markdown) are never stored: they are not downloadable.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

STORABLE_TYPES = ("pdf", "docx", "pptx")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StoredFileError(Exception):
    """The stored copy is missing or does not match its hash. ``code`` is safe to log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def relative_path(sha256: str, source_type: str) -> str:
    if not _SHA256.fullmatch(sha256) or source_type not in STORABLE_TYPES:
        raise ValueError("not a storable file")
    return f"{sha256[:2]}/{sha256}.{source_type}"


def store(root: Path, sha256: str, source_type: str, content: bytes) -> str | None:
    """Write ``content`` under ``root`` once; return its relative path.

    None for a type that is not stored. Writes to a temporary file and renames it, so a
    reader never sees a partial file; an existing copy with the same name is kept.
    """
    if source_type not in STORABLE_TYPES:
        return None
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("content does not match its hash")
    relative = relative_path(sha256, source_type)
    target = root / relative
    if target.is_file():
        return relative
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return relative


def read(root: Path, stored_path: str, sha256: str) -> bytes:
    """The stored bytes of a source, checked against its hash."""
    base = root.resolve()
    path = (base / stored_path).resolve()
    if not path.is_relative_to(base) or path == base:
        raise StoredFileError("bad_path")
    try:
        content = path.read_bytes()
    except OSError:
        raise StoredFileError("file_missing") from None
    if hashlib.sha256(content).hexdigest() != sha256:
        raise StoredFileError("hash_mismatch")
    return content
