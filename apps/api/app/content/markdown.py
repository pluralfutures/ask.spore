"""Image references in Markdown (P2B-06): what RAGFlow would load, and how to remove it."""

from __future__ import annotations

import re

# An image reference in Markdown. RAGFlow's Markdown parser loads every image it finds
# while parsing: an http(s) one is fetched from the internet, any other is opened as a
# path inside the RAGFlow container (phase-2b-findings.md section 1). The patterns are a
# superset of RAGFlow's own (`![..](`, a quoted `src=` on any tag, `<img>`), plus the
# reference form `![..][..]`, so nothing it would load gets through.
IMAGE_REFERENCE = re.compile(r"!\[[^\]]*\][(\[]|\bsrc\s*=|<img\b", re.IGNORECASE)
_IMAGE_INLINE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_IMAGE_BY_REFERENCE = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def strip_image_references(markdown: str) -> str:
    """Markdown with every image reference taken out (P2B-06, second layer).

    A crawled or fetched page is not refused for holding an image, as an uploaded file is;
    the references are removed before the page goes to RAGFlow, so its parser has nothing to
    load. An image keeps its alt text as plain text. Whatever the patterns still find after
    that (odd syntax, a ``src=`` on another tag) loses its whole line, so the result never
    matches the check ``check_file_content`` applies to an upload.
    """
    text = _IMAGE_INLINE.sub(r"\1", markdown)
    text = _IMAGE_BY_REFERENCE.sub(r"\1", text)
    text = _IMG_TAG.sub("", text)
    if IMAGE_REFERENCE.search(text):
        text = "\n".join(line for line in text.split("\n") if not IMAGE_REFERENCE.search(line))
    return text
