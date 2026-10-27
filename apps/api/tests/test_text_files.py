"""P2B-06: Markdown and plain-text files as sources: what an upload must be, that an
uploaded file keeps a stored copy for download and a fetched page does not, that the file
list and the download serve them, and that a mislabelled file is refused. Synthetic content
only. The real RAGFlow parse of each type is a release check on the Instance (findings)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.content.fetch import Fetched
from app.content.ingest import (
    IngestError,
    SourceFile,
    check_file_content,
    from_fetched,
    load_path,
)
from app.content.models import SOURCE_TYPES
from app.content.store import is_file
from tests.test_api import api
from tests.test_auth import auth
from tests.test_content_console import API, Console, console
from tests.test_files import Files, files
from tests.test_ingest import PDF, env, meta, source_row

__all__ = ["api", "auth", "console", "env", "files"]  # fixtures

pytestmark = pytest.mark.usefixtures("database")

MARKDOWN = (
    b"# Synthetic heading\n\nSynthetic paragraph with a table.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
)
TEXT = b"Synthetic plain text, line one.\nSynthetic line two.\n"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- what a file must be ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "content", "media"),
    [
        ("markdown", MARKDOWN, None),
        ("markdown", MARKDOWN, "text/markdown"),
        ("markdown", MARKDOWN, "text/x-markdown"),
        ("markdown", MARKDOWN, "text/plain"),  # some browsers say so for .md
        ("markdown", MARKDOWN, "application/octet-stream"),
        ("markdown", MARKDOWN, ""),
        ("text", TEXT, "text/plain"),
        ("text", TEXT, "text/plain; charset=utf-8"),
        ("text", TEXT, "text/markdown"),
        ("text", b"\xef\xbb\xbfSynthetic text with a byte-order mark", None),
        ("text", "Synthetic Café, naïve, 日本語".encode(), None),
        ("pdf", b"%PDF-1.7\nsynthetic", "application/pdf"),
        ("docx", b"PK\x03\x04synthetic", DOCX_MEDIA),
    ],
)
def test_a_file_that_is_what_it_says_is_accepted(
    kind: str, content: bytes, media: str | None
) -> None:
    check_file_content(kind, content, media)


@pytest.mark.parametrize(
    ("kind", "content", "media", "code"),
    [
        # A binary file renamed .txt or .md.
        ("text", PDF.read_bytes(), None, "not_text"),
        ("markdown", b"PK\x03\x04\x00\x00synthetic", None, "not_text"),
        ("text", b"Synthetic\x00text", None, "not_text"),
        ("text", b"\xff\xfe\x00S\x00y\x00", None, "not_text"),  # UTF-16
        ("text", "Synthetic café".encode("latin-1"), None, "not_text"),  # not UTF-8
        ("text", b"", None, "not_text"),
        ("markdown", b"  \n\t\n", None, "not_text"),
        # Text renamed .pdf, .docx or .pptx.
        ("pdf", TEXT, None, "type_mismatch"),
        ("docx", TEXT, None, "type_mismatch"),
        ("pptx", MARKDOWN, None, "type_mismatch"),
        # A declared type that names another kind of file.
        ("markdown", MARKDOWN, "application/pdf", "type_mismatch"),
        ("text", TEXT, "application/pdf", "type_mismatch"),
        ("text", TEXT, DOCX_MEDIA, "type_mismatch"),
        ("pdf", b"%PDF-1.7\nsynthetic", "text/plain", "type_mismatch"),
    ],
)
def test_a_mislabelled_file_is_refused_with_a_code_only(
    kind: str, content: bytes, media: str | None, code: str
) -> None:
    with pytest.raises(IngestError) as refused:
        check_file_content(kind, content, media)
    assert refused.value.code == code
    assert "Synthetic" not in str(refused.value)  # never the file's own text


# RAGFlow's Markdown parser loads every image it finds: an http(s) one from the internet,
# any other as a path inside its container (findings 2B section 1). Each form is refused.
@pytest.mark.parametrize(
    "line",
    [
        b"![Synthetic chart](https://img.example.org/chart.png)",
        b"![](http://img.example.org/a.png)",
        b"![Synthetic](/etc/synthetic.png)",  # a local path
        b"![Synthetic](data:image/png;base64,AAAA)",
        b"![Synthetic\nchart](https://img.example.org/a.png)",  # alt text over two lines
        b"![Synthetic][chart]\n\n[chart]: https://img.example.org/a.png",  # reference form
        b'<img src="https://img.example.org/a.png">',
        b"<IMG SRC=https://img.example.org/a.png>",  # unquoted, upper case
        b"<img\n  alt='Synthetic'\n  src='a.png'>",  # over several lines
        b'<picture><source src="https://img.example.org/a.webp"></picture>',  # any src=
    ],
)
def test_markdown_with_an_image_reference_is_refused_with_a_code_only(line: bytes) -> None:
    content = b"# Synthetic\n\nSynthetic paragraph.\n\n" + line + b"\n"
    for body in (content, b"\xef\xbb\xbf" + content):  # with and without a BOM
        with pytest.raises(IngestError) as refused:
            check_file_content("markdown", body, "text/markdown")
        assert refused.value.code == "image_reference"
        assert "example.org" not in str(refused.value)  # never the reference itself
        assert "Synthetic" not in str(refused.value)


@pytest.mark.parametrize(
    "line",
    [
        b"[Synthetic link](https://example.org/report)",  # a plain link is not an image
        b"Synthetic exclamation! [Synthetic](https://example.org/)",
        b"Synthetic [footnote][1]\n\n[1]: https://example.org/",
        b"Synthetic source code mentions srcset only in prose.",
    ],
)
def test_markdown_with_links_but_no_image_is_accepted(line: bytes) -> None:
    check_file_content("markdown", b"# Synthetic\n\n" + line + b"\n", "text/markdown")


def test_plain_text_with_image_syntax_is_accepted() -> None:
    # RAGFlow parses .txt with its text parser, which loads nothing.
    check_file_content("text", b"Synthetic ![x](https://example.org/a.png)\n", "text/plain")


def test_load_path_refuses_markdown_with_an_image(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"# Synthetic\n\n![](https://img.example.org/a.png)\n")
    with pytest.raises(IngestError) as refused:
        load_path(path)
    assert refused.value.code == "image_reference"


def test_load_path_takes_md_markdown_and_txt_as_files(tmp_path: Path) -> None:
    for name, kind, content in (
        ("notes.md", "markdown", MARKDOWN),
        ("notes.MARKDOWN", "markdown", MARKDOWN),
        ("notes.txt", "text", TEXT),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        loaded = load_path(path)
        assert (loaded.type, loaded.as_file) == (kind, True)
    bad = tmp_path / "binary.txt"
    bad.write_bytes(PDF.read_bytes())
    with pytest.raises(IngestError) as refused:
        load_path(bad)
    assert refused.value.code == "not_text"


def test_a_fetched_page_is_never_a_file_and_plain_text_is_not_fetched() -> None:
    def fetched(url: str, media: str, body: bytes) -> Fetched:
        return Fetched(url=url, content=body, content_type=media, headers={}, status=200)  # type: ignore[call-arg]

    page = from_fetched(fetched("https://example.org/a.md", "text/markdown", MARKDOWN))
    assert (page.type, page.as_file) == ("markdown", False)
    for url, media in (
        ("https://example.org/a.txt", "text/plain"),
        ("https://example.org/a", "text/plain"),
    ):
        with pytest.raises(IngestError) as refused:
            from_fetched(fetched(url, media, TEXT))
        assert refused.value.code == "unsupported_type"


def test_text_is_a_source_type_and_a_stored_text_or_markdown_source_is_a_file() -> None:
    assert "text" in SOURCE_TYPES
    assert is_file("pdf", None) and is_file("markdown", "ab/abc.markdown") and is_file("text", "x")
    assert not is_file("markdown", None) and not is_file("html", None)


# --- the register keeps a copy of an uploaded file and not of a page ---------------------------


async def test_an_uploaded_markdown_or_text_file_keeps_a_stored_copy_and_may_be_downloadable(
    env: Any, admin_conn: Any, tmp_path: Path
) -> None:
    _, run = env
    for kind, name, content in (("markdown", "notes.md", MARKDOWN), ("text", "notes.txt", TEXT)):
        path = tmp_path / "in" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        flagged = meta("sample-web")
        flagged = type(flagged)(**{**flagged.__dict__, "downloadable": True, "title": name})
        result = await run(load_path(path), flagged, content_root=tmp_path / "root")
        row = await source_row(admin_conn, result.source_id)
        sha = hashlib.sha256(content).hexdigest()
        assert (row["type"], row["downloadable"]) == (kind, True)
        assert row["stored_path"] == f"{sha[:2]}/{sha}.{kind}"
        assert (tmp_path / "root" / row["stored_path"]).read_bytes() == content


async def test_a_page_has_no_stored_copy_even_when_it_is_markdown(
    env: Any, admin_conn: Any, tmp_path: Path
) -> None:
    _, run = env
    page = SourceFile("page.md", "markdown", MARKDOWN)  # as_file stays False: not given as a file
    result = await run(page, meta("sample-web"), content_root=tmp_path)
    assert (await source_row(admin_conn, result.source_id))["stored_path"] is None


# --- the content console's upload ---------------------------------------------------------------


async def _propose(
    console: Console, name: str, content: bytes, media: str, **fields: Any
) -> httpx.Response:
    await console.roles("content_editor")
    files_ = {"file": (name, content, media)}
    data = {**__import__("tests.test_content_console", fromlist=["PROPOSAL"]).PROPOSAL, **fields}
    return await console.editor().post(f"{API}/sources", data=data, files=files_)


@pytest.mark.parametrize(
    ("name", "content", "media", "kind"),
    [
        ("notes.md", MARKDOWN, "text/markdown", "markdown"),
        ("notes.md", MARKDOWN, "application/octet-stream", "markdown"),
        ("notes.markdown", MARKDOWN, "text/plain", "markdown"),
        ("notes.txt", TEXT, "text/plain", "text"),
        ("notes.TXT", TEXT, "text/plain; charset=utf-8", "text"),
    ],
    ids=["md", "md-generic", "markdown-suffix", "txt", "txt-upper-charset"],
)
async def test_an_editor_uploads_a_markdown_or_text_file(
    console: Console, name: str, content: bytes, media: str, kind: str
) -> None:
    response = await _propose(console, name, content, media, downloadable="true")
    assert response.status_code == 201, response.text
    row = await console.auth.admin.fetchrow(
        "SELECT type, status, stored_path, downloadable FROM sources WHERE id = $1",
        UUID(response.json()["source_id"]),
    )
    sha = hashlib.sha256(content).hexdigest()
    assert (row["type"], row["status"], row["downloadable"]) == (kind, "proposed", True)
    assert row["stored_path"] == f"{sha[:2]}/{sha}.{kind}"


@pytest.mark.parametrize(
    ("name", "content", "media", "code"),
    [
        ("notes.txt", PDF.read_bytes(), "text/plain", "not_text"),  # a PDF renamed .txt
        ("notes.md", b"PK\x03\x04\x00\x00binary", "text/markdown", "not_text"),
        ("notes.txt", b"nul\x00byte", "text/plain", "not_text"),
        ("notes.txt", "café".encode("latin-1"), "text/plain", "not_text"),
        ("notes.md", MARKDOWN, "application/pdf", "type_mismatch"),  # .md declared as a PDF
        ("notes.txt", TEXT, "application/pdf", "type_mismatch"),
        ("report.pdf", TEXT, "application/pdf", "type_mismatch"),  # text renamed .pdf
        ("report.docx", MARKDOWN, DOCX_MEDIA, "type_mismatch"),
        ("notes.rtf", TEXT, "text/plain", "unsupported_type"),
        (
            "notes.md",
            b"# Synthetic\n\n![](https://img.example.org/a.png)\n",
            "text/markdown",
            "image_reference",
        ),
    ],
    ids=[
        "pdf-as-txt",
        "zip-as-md",
        "nul-in-txt",
        "latin1-txt",
        "md-declared-pdf",
        "txt-declared-pdf",
        "text-as-pdf",
        "text-as-docx",
        "rtf",
        "md-with-image",
    ],
)
async def test_a_mislabelled_upload_is_refused_and_nothing_is_recorded(
    console: Console, name: str, content: bytes, media: str, code: str
) -> None:
    response = await _propose(console, name, content, media)
    assert (response.status_code, response.json()["detail"]) == (422, code)
    assert await console.auth.admin.fetchval("SELECT count(*) FROM sources") == 0
    assert not console.e.content_root.exists()  # nothing staged either
    assert console.e.fake.uploads == []


async def test_a_refused_upload_logs_a_code_and_no_file_text(
    console: Console, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    await _propose(console, "secret-notes.txt", b"Synthetic secret\x00body", "text/plain")
    out = capsys.readouterr()
    text = out.out + out.err
    assert "not_text" in text
    assert "Synthetic secret" not in text and "secret-notes" not in text


# --- the file list and the download --------------------------------------------------------------


async def _stored(files: Files, kind: str, content: bytes, **kw: Any) -> UUID:
    """A source of ``kind`` with our copy stored the way the register stores it."""
    from app.content import store

    sha = hashlib.sha256(content).hexdigest()
    path = store.stage(files.root, sha, kind, content)
    source_id: UUID = await files.admin.fetchval(
        "INSERT INTO sources (type, title, publisher, published_on, canonical_url, licence_basis, "
        "tags, status, file_sha256, ragflow_document_ids, downloadable, stored_path, approved_at) "
        "VALUES ($1, $2, 'Synthetic Publisher', '2026-03-01', $3, 'public', ARRAY['p2b06'], "
        "'ingested', $4, '{}'::jsonb, $5, $6, now()) RETURNING id",
        kind,
        kw.get("title", f"Synthetic {kind}"),
        kw.get("url", "https://example.org/synthetic-file"),
        sha,
        kw.get("downloadable", True),
        path if kw.get("stored", True) else None,
    )
    files.created.append(source_id)
    return source_id


@pytest.fixture
async def own(files: Files) -> Files:
    files.workspace = await files.api.world.new_workspace(["p2b06"])
    return files


async def test_uploaded_markdown_and_text_files_are_listed_as_files_and_pages_stay_sites(
    own: Files,
) -> None:
    md = await _stored(own, "markdown", MARKDOWN, title="Synthetic notes")
    txt = await _stored(own, "text", TEXT, title="Synthetic text")
    page = await _stored(  # a crawled page: markdown, no stored copy
        own, "markdown", MARKDOWN + b"page", stored=False, downloadable=False,
        url="https://site-a.example/page",
    )  # fmt: skip
    body = (await own.api.request("GET", f"/workspaces/{own.workspace}/files")).json()
    listed = {f["id"]: f for f in body["files"]}
    assert set(listed) == {str(md), str(txt)}
    assert str(page) not in listed
    assert listed[str(md)]["type"] == "markdown" and listed[str(md)]["downloadable"] is True
    assert listed[str(txt)]["type"] == "text"
    assert [s["site"] for s in body["sites"]] == ["site-a.example"]
    summary = (await own.api.request("GET", f"/workspaces/{own.workspace}/summary")).json()
    assert summary["document_count"] == 3  # two files and one site


@pytest.mark.parametrize(
    ("kind", "content", "media", "suffix"),
    [("markdown", MARKDOWN, "text/markdown", ".md"), ("text", TEXT, "text/plain", ".txt")],
)
async def test_a_markdown_or_text_file_downloads_as_the_stored_bytes(
    own: Files, kind: str, content: bytes, media: str, suffix: str
) -> None:
    source = await _stored(own, kind, content, title="Synthetic Notes 2026")
    link = await own.link(source)
    assert link.status_code == 201, link.text
    served = await own.fetch(link.json()["url"])
    assert served.status_code == 200
    assert served.content == content
    assert served.headers["content-type"].split(";")[0] == media
    assert "charset=utf-8" in served.headers["content-type"]
    assert served.headers["x-content-type-options"] == "nosniff"
    disposition = served.headers["content-disposition"]
    assert disposition.startswith("attachment") and disposition.endswith(f'{suffix}"')
    assert "upload" not in disposition  # never the original file name


async def test_a_page_and_a_gated_file_are_not_downloadable(own: Files) -> None:
    page = await _stored(own, "markdown", MARKDOWN, stored=False, downloadable=False)
    gated = await _stored(own, "text", TEXT, downloadable=False)
    assert (await own.link(page)).status_code == 404  # not a file of the workspace
    refused = await own.link(gated)
    assert (refused.status_code, refused.json()["detail"]) == (403, "not_downloadable")


async def test_download_audit_and_logs_carry_ids_and_no_file_text(
    own: Files, capsys: pytest.CaptureFixture[str]
) -> None:
    source = await _stored(own, "text", TEXT, title="Synthetic Confidential Title")
    capsys.readouterr()
    served = await own.fetch((await own.link(source)).json()["url"])
    assert served.status_code == 200
    out = capsys.readouterr()
    assert "Synthetic plain text" not in out.out + out.err
    assert "Synthetic Confidential Title" not in out.out + out.err
    audited = await own.audit("download")
    assert audited and "Synthetic plain text" not in json.dumps(audited, default=str)


async def test_the_operator_may_open_the_download_gate_of_a_stored_file_only(
    own: Files,
) -> None:
    from app.content.store import is_file

    assert is_file("text", "ab/abc.text") and not is_file("text", None)
    assert is_file("markdown", "ab/abc.markdown") and not is_file("markdown", None)
