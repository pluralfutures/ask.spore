"""P2B-06 second layer: a crawled or fetched Markdown page never reaches RAGFlow with an image
reference in it, because RAGFlow's Markdown parser loads every image it finds. An uploaded
file holding one is refused instead (tests/test_text_files.py). Synthetic content only."""

from __future__ import annotations

import pytest

from app.content.crawler import render
from app.content.fetch import Fetched
from app.content.ingest import IngestError, check_file_content, from_fetched
from app.content.markdown import IMAGE_REFERENCE, strip_image_references

FORMS = [
    "![Synthetic chart](https://img.example.org/a.png)",
    "![](https://img.example.org/a.png)",
    "![Synthetic local](../private/a.png)",
    "![Synthetic data](data:image/png;base64,AAAA)",
    '![Synthetic titled](https://img.example.org/a.png "A title")',
    "![Synthetic by reference][img]",
    '<img src="https://img.example.org/a.png" alt="Synthetic">',
    "<IMG SRC='https://img.example.org/a.png'>",
    '<picture><source src="https://img.example.org/a.webp"></picture>',
    "![Odd (nested) parens](https://img.example.org/a_(1).png)",
]


@pytest.mark.parametrize("line", FORMS)
def test_no_image_reference_survives_the_strip(line: str) -> None:
    page = f"# Synthetic title\n\nBefore.\n\n{line}\n\nAfter.\n"
    stripped = strip_image_references(page)
    assert not IMAGE_REFERENCE.search(stripped)
    assert "example.org" not in stripped and "private/a.png" not in stripped
    assert "Before." in stripped and "After." in stripped and "# Synthetic title" in stripped
    # What is left would pass the check an upload must pass.
    check_file_content("markdown", stripped.encode(), "text/markdown")


def test_an_image_keeps_its_alt_text_and_links_are_untouched() -> None:
    page = (
        "See ![Synthetic chart](https://img.example.org/a.png) and [a link](https://example.org/r)."
    )
    assert (
        strip_image_references(page) == "See Synthetic chart and [a link](https://example.org/r)."
    )


def test_a_page_without_images_is_unchanged() -> None:
    page = "# Synthetic\n\nSynthetic exclamation! [x](https://example.org/)\n\n[1]: https://example.org/\n"
    assert strip_image_references(page) == page


def test_the_crawler_renders_pages_without_image_references() -> None:
    html = (
        b"<html><head><title>Synthetic page</title></head><body><article>"
        b"<h1>Synthetic heading</h1><p>Synthetic paragraph about a report, long enough to be "
        b"readable content for the extractor to keep as the main text of this page.</p>"
        b"<p>![Synthetic literal](https://img.example.org/a.png) typed in the text.</p>"
        b'<img src="https://img.example.org/b.png" alt="Synthetic">'
        b"</article></body></html>"
    )
    rendered = render(html, "https://site.example/page")
    assert rendered is not None
    _, markdown = rendered
    assert not IMAGE_REFERENCE.search(markdown)
    assert "b.png" not in markdown  # the <img> tag is gone (the extractor drops it)


def _fetched(body: bytes) -> Fetched:
    return Fetched(
        url="https://example.org/page.md",
        content=body,
        content_type="text/markdown",
        headers={},
        status=200,
    )  # type: ignore[call-arg]


def test_a_fetched_markdown_page_has_its_images_removed_not_refused() -> None:
    body = b"# Synthetic\n\nText.\n\n![](https://img.example.org/a.png)\n"
    page = from_fetched(_fetched(body))
    assert (page.type, page.as_file) == ("markdown", False)
    assert not IMAGE_REFERENCE.search(page.content.decode())
    assert b"Text." in page.content


def test_a_fetched_markdown_page_that_was_only_images_is_empty() -> None:
    with pytest.raises(IngestError) as refused:
        from_fetched(_fetched(b"<img src='https://img.example.org/a.png'>\n"))
    assert refused.value.code == "empty"
