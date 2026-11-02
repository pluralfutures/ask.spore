"""Generate the synthetic uploaded-crawl ZIPs in this directory (Phase 2SR01).

Every company, product and sentence below is invented. The pages follow the shape of the
files markdown.new (Cloudflare's Markdown for Agents) emits, as recorded in the Phase
2SR01 spec ("The ZIP"): a leading ``<!-- Source: <url> -->`` comment, a front-matter block
with ``title`` and a nested ``meta`` mapping, no date, and a body that keeps the site's
navigation and footer. The host is ``www.example.org`` (a reserved domain that resolves
to a public address, so the release drill can register it). Regenerate with:

    python3 packages/eval/fixtures/uploads/make_uploads.py

The output is byte-for-byte reproducible (fixed member timestamps);
``apps/api/tests/test_site_uploads.py`` checks that the committed files match.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
HOST = "https://www.example.org"
STAMP = (2026, 10, 30, 12, 0, 0)
NAV = (
    f"[](https://www.example.org/)\n\n"
    f"- [Products]({HOST}/Products)\n- [Recipes]({HOST}/Recipes)\n- [Contact]({HOST}/Contact)\n"
)
FOOTER = "\n\n© 2026 Synthetic Pantry Co. (invented) · [Buy now](https://www.example.org/shop)\n"


def page(
    path: str,
    title: str | None,
    text: str,
    *,
    comment: bool = True,
    block: bool = True,
    extra: str = "",
) -> str:
    head = f"<!-- Source: {HOST}{path} -->\n\n" if comment else ""
    if block:
        lines = ["---"]
        if title is not None:
            lines.append(f'title: "{title}"')
        lines += [
            "meta:",
            f'  description: "Synthetic description of {path}"',
            '  keywords: "synthetic, pantry, invented"',
        ]
        if extra:
            lines.append(extra)
        lines.append("---")
        head += "\n".join(lines) + "\n\n"
    return head + NAV + "\n# " + (title or "Untitled") + "\n\n" + text + FOOTER


GRAVY = page(
    "/Products/Gravies",
    "Synthetic Pantry - Gravies and Au Jus",
    "Our invented gravy base is simmered for six hours from roasted synthetic stock. "
    "Each 400 g tub makes 4 litres of gravy.",
)
BROTH = page(
    "/Products/Broth",
    "Synthetic Pantry - Broth Concentrate",
    "The invented broth concentrate dissolves in hot water; one spoon makes 250 ml.",
)
SOUP = page(
    "/Recipes/Soup",
    "Synthetic Pantry - Winter Soup",
    "Combine two litres of invented broth with root vegetables and simmer for forty minutes.",
)


def write(name: str, members: list[tuple[str, bytes | str]], **kinds: int) -> None:
    """``kinds`` maps a member name to its Unix mode bits or 0x1 for the encrypted flag."""
    path = OUT / name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, content in members:
            info = zipfile.ZipInfo(member, date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 << 16) if not member.endswith("/") else (0o40755 << 16)
            if member in kinds and kinds[member] != 0x1:
                info.external_attr = kinds[member] << 16
            data = content.encode() if isinstance(content, str) else content
            archive.writestr(info, data)
    encrypted = [m for m, kind in kinds.items() if kind == 0x1]
    if encrypted:
        _flag_encrypted(path, encrypted)


def _flag_encrypted(path: Path, members: list[str]) -> None:
    """Set the "encrypted" flag bit of ``members`` in the local and central headers
    (``zipfile`` clears it when writing; the content stays plain)."""
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        offsets = [archive.getinfo(m).header_offset for m in members]
    for offset in offsets:
        raw[offset + 6] |= 0x1  # local file header: general purpose bit flag
    position = raw.find(b"PK\x01\x02")
    while position != -1:
        name_length = int.from_bytes(raw[position + 28 : position + 30], "little")
        name = bytes(raw[position + 46 : position + 46 + name_length]).decode()
        if name in members:
            raw[position + 8] |= 0x1  # central directory header: general purpose bit flag
        position = raw.find(b"PK\x01\x02", position + 4)
    path.write_bytes(bytes(raw))


def inner_zip() -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("inner.md", date_time=STAMP), GRAVY)
    return buffer.getvalue()


def main() -> None:
    good = ("site/Products/Gravies.md", GRAVY)
    # Exactly as markdown.new emits it, with the side files a Mac and a converter leave.
    write(
        "markdown-new.zip",
        [
            ("site/", b""),
            good,
            ("site/Products/Broth.md", BROTH),
            ("site/Recipes/Soup.markdown", SOUP),
            ("site/.DS_Store", b"\x00\x00\x00\x01Bud1"),
            ("__MACOSX/site/._Gravies.md", b"\x00\x05\x16\x07"),
            ("site/logo.png", b"\x89PNG\r\n\x1a\n"),
            ("site/notes.txt", "synthetic notes, not a page"),
        ],
    )
    # A second, partial upload: Gravies changed, Broth unchanged, a new page; Soup absent.
    write(
        "markdown-new-second.zip",
        [
            (
                "site/Products/Gravies.md",
                GRAVY.replace("six hours", "eight hours"),
            ),
            ("site/Products/Broth.md", BROTH.replace("Synthetic description", "New meta")),
            (
                "site/Products/Stock.md",
                page(
                    "/Products/Stock",
                    "Synthetic Pantry - Stock Cubes",
                    "Invented stock cubes, twelve per box, each for 500 ml of stock.",
                ),
            ),
        ],
    )
    # The first crawl again without the soup page (a full upload withdraws it).
    write("markdown-new-without-soup.zip", [good, ("site/Products/Broth.md", BROTH)])

    # One member per member-level code, beside a good page.
    write(
        "off-site.zip",
        [good, ("site/away.md", page("/x", "Away", "Elsewhere.").replace(HOST, "https://other.example"))],
    )
    write("url-missing.zip", [good, ("site/no-url.md", page("/x", "No URL", "Body.", comment=False))])
    write(
        "bad-date.zip",
        [good, ("site/dated.md", page("/Dated", "Dated", "Body.", extra="date: 14 March 2026"))],
    )
    write(
        "dated.zip",
        [good, ("site/dated.md", page("/Dated", "Dated", "Body.", extra="date: 2026-03-14"))],
    )
    write(
        "url-mismatch.zip",
        [good, ("site/mismatch.md", page("/One", "Mismatch", "Body.", extra=f"url: {HOST}/Two"))],
    )
    write(
        "comment-no-block.zip",
        [good, ("site/plain.md", page("/Plain", "Plain heading page", "Body.", block=False))],
    )
    write(
        "unterminated-block.zip",
        [good, ("site/open.md", f"<!-- Source: {HOST}/Open -->\n\n---\ntitle: \"Open\"\n\nBody.\n")],
    )
    write(
        "empty-body.zip",
        [good, ("site/empty.md", f"<!-- Source: {HOST}/Empty -->\n\n---\ntitle: \"E\"\n---\n\n")],
    )
    write("not-utf8.zip", [good, ("site/latin1.md", page("/Latin", "Caf\xe9", "Body.").encode("latin-1"))])
    write(
        "oversize-member.zip",
        [good, ("site/huge.md", page("/Huge", "Huge", "a" * (5 * 1024 * 1024)))],
    )
    write(
        "special-category.zip",
        [good, ("site/health.md", page("/health/clinic", "Clinic opening hours", "Opening times."))],
    )
    # Whole-upload refusals.
    write("dotdot-name.zip", [good, ("site/../escape.md", GRAVY)])
    write("absolute-name.zip", [good, ("/etc/escape.md", GRAVY)])
    write("nested-zip.zip", [good, ("site/inner.zip", inner_zip())])
    write("zip-named-md.zip", [good, ("site/inner.md", inner_zip())])
    write("symlink.zip", [good, ("site/link.md", "/etc/passwd")], **{"site/link.md": 0o120777})
    write("encrypted.zip", [good, ("site/secret.md", GRAVY)], **{"site/secret.md": 0x1})
    write(
        "duplicate-url.zip",
        [good, ("site/copy/Gravies.md", GRAVY.replace("six hours", "five hours"))],
    )
    write("no-pages.zip", [("site/notes.txt", "no pages here")])
    (OUT / "not-a-zip.zip").write_bytes(b"this is not a ZIP archive\n")


if __name__ == "__main__":
    sys.exit(main())
