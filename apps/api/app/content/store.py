"""Our own copies of ingested files, for downloads (P1a-14).

RAGFlow is internal and its endpoints are never exposed through our API (CLAUDE.md),
so downloads cannot be served from it. At ingestion, a PDF, DOCX or PPTX file is
written under ``[files] content_root`` as ``<first two hex digits>/<sha256>.<type>``:
named by its content hash, never by the original file name, so neither the path nor a
log line carries a client document's name. ``sources.stored_path`` records the relative
path (a check constraint ties it to ``file_sha256``). Reading checks that the path stays
under the root and that the bytes still hash to ``file_sha256``.

Pages (HTML, Markdown) are never downloadable, so they never get a ``stored_path``.
Since P1b-02 every proposed file, pages included, is also *staged* here by the same
naming rule (``stage``): the ingestion worker runs in its own container and reads the
file from this store, so a job's payload never carries document contents. A licence or
permission letter (P1b-01) is kept as ``licences/<sha256>.<ext>`` (``store_licence``), and
a crawled page's raw HTML snapshot (P1b-04, provenance) as ``snapshots/<sha256>.html``
(``store_snapshot``); neither ever goes to RAGFlow.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

STORABLE_TYPES = ("pdf", "docx", "pptx")
STAGED_TYPES = ("pdf", "docx", "pptx", "html", "markdown")
LICENCE_DIR = "licences"
SNAPSHOT_DIR = "snapshots"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXTENSION = re.compile(r"^[a-z0-9]{1,8}$")


class StoredFileError(Exception):
    """The stored copy is missing or does not match its hash. ``code`` is safe to log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def relative_path(sha256: str, source_type: str) -> str:
    if not _SHA256.fullmatch(sha256) or source_type not in STAGED_TYPES:
        raise ValueError("not a storable file")
    return f"{sha256[:2]}/{sha256}.{source_type}"


def _write_once(root: Path, relative: str, content: bytes) -> None:
    """Write to a temporary file and rename it, so a reader never sees a partial file;
    an existing copy with the same name is kept."""
    target = root / relative
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def stage(root: Path, sha256: str, source_type: str, content: bytes) -> str:
    """Write a proposed file of any source type under ``root``; return its relative path."""
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("content does not match its hash")
    relative = relative_path(sha256, source_type)
    _write_once(root, relative, content)
    return relative


def store(root: Path, sha256: str, source_type: str, content: bytes) -> str | None:
    """Write ``content`` under ``root`` once; return its relative path for downloads.

    None for a type that is not downloadable (the file is still staged).
    """
    relative = stage(root, sha256, source_type, content)
    return relative if source_type in STORABLE_TYPES else None


def store_licence(root: Path, content: bytes, extension: str) -> str:
    """Keep a licence or permission letter as ``licences/<sha256>.<ext>``; return the path."""
    extension = extension.lower().lstrip(".")
    if not _EXTENSION.fullmatch(extension) or not content:
        raise ValueError("not a licence file")
    relative = f"{LICENCE_DIR}/{hashlib.sha256(content).hexdigest()}.{extension}"
    _write_once(root, relative, content)
    return relative


def store_snapshot(root: Path, content: bytes) -> str:
    """Keep a crawled page's raw HTML as ``snapshots/<sha256>.html``; return the path."""
    if not content:
        raise ValueError("empty snapshot")
    relative = f"{SNAPSHOT_DIR}/{hashlib.sha256(content).hexdigest()}.html"
    _write_once(root, relative, content)
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


def remove(root: Path, relative: str) -> bool:
    """Delete a staged or stored copy (withdrawal, P1b-03); True when a file was removed."""
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or path == base:
        raise StoredFileError("bad_path")
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True
