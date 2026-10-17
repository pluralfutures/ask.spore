"""Citation markers: ``[n]`` in answers refers to context passage ``n``.

``MarkerFilter`` rewrites the answer as it streams, so the text the user sees live
is the text that is stored: markers that reference a passage are kept, dangling
markers (``[12]`` with ten passages, ``[0]``) are dropped, and groups such as
``[1, 3]`` are normalised to ``[1][3]``. Bracketed text that is not a marker
(``[sic]``, ``[2025 figures]``) passes through unchanged.
"""

from __future__ import annotations

import re

_GROUP = re.compile(r"^\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*$")
_MAX_PENDING = 24  # longest marker group held back while streaming
_ANY_MARKER = re.compile(r"\[(\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*)\]")


class MarkerFilter:
    def __init__(self, passage_count: int) -> None:
        self._valid = range(1, passage_count + 1)
        self._pending = ""
        self.cited: list[int] = []  # valid markers in order of first use

    def _resolve(self, inner: str) -> str:
        kept = []
        for part in inner.split(","):
            n = int(part)
            if n in self._valid:
                kept.append(n)
                if n not in self.cited:
                    self.cited.append(n)
        return "".join(f"[{n}]" for n in kept)

    def feed(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            if self._pending:
                if char == "]":
                    inner = self._pending[1:]
                    out.append(
                        self._resolve(inner) if _GROUP.match(inner) else self._pending + char
                    )
                    self._pending = ""
                elif (char.isdigit() or char in ", ") and len(self._pending) < _MAX_PENDING:
                    self._pending += char
                else:
                    out.append(self._pending)
                    self._pending = ""
                    if char == "[":
                        self._pending = char
                    else:
                        out.append(char)
            elif char == "[":
                self._pending = char
            else:
                out.append(char)
        return "".join(out)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest


def filter_markers(text: str, passage_count: int) -> tuple[str, list[int]]:
    """Non-streaming form of ``MarkerFilter``: the cleaned text and the cited markers."""
    markers = MarkerFilter(passage_count)
    cleaned = markers.feed(text) + markers.flush()
    return cleaned, markers.cited


def strip_markers(text: str) -> str:
    """Remove every marker, e.g. from earlier answers sent back as history."""
    return _ANY_MARKER.sub("", text)
