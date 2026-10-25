"""P2A-11: the public files Caddy serves outside the application and its consent gate.

``/.well-known/security.txt`` (RFC 9116) and ``/security-disclosure`` come from the web
build's ``public/`` directory as plain files; ``/trust`` 404s until the owner sets the
deploy-time flag ``ASKSPORE_TRUST_PAGE=published``. These tests read the files and the
Caddyfile; when a ``caddy`` binary is available (``CADDY_BIN`` or on ``PATH``) the last one
also runs the real Caddyfile over HTTP. The Playwright check (``apps/web/e2e/publicFiles``)
proves the same routes load without sign-in or a consent redirect.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
CADDYFILE = REPO / "infra" / "caddy" / "Caddyfile"
PUBLIC = REPO / "apps" / "web" / "public"
SECURITY_TXT = PUBLIC / ".well-known" / "security.txt"
DISCLOSURE = PUBLIC / "security-disclosure.html"
DRAFT = REPO / "design" / "compliance" / "security-disclosure.md"
HOST = "askspore.myceliumgastronomy.com"

# RFC 9116 §2.5 field names; anything else is a typo or an extension we do not use.
KNOWN_FIELDS = {
    "acknowledgments",
    "canonical",
    "contact",
    "encryption",
    "expires",
    "hiring",
    "policy",
    "preferred-languages",
    "csaf",
}
_FIELD = re.compile(r"^([A-Za-z-]+): (\S.*)$")


class SecurityTxtError(ValueError):
    pass


def parse_security_txt(text: str, *, now: datetime) -> dict[str, list[str]]:
    """Fields of an unsigned security.txt, refused unless it meets RFC 9116's musts
    (Contact at least once, Expires exactly once and in the future) and our rule that
    Expires is at most a year away."""
    if not text.endswith("\n"):
        raise SecurityTxtError("the last line has no line break")
    fields: dict[str, list[str]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        match = _FIELD.match(line)
        if not match:
            raise SecurityTxtError(f"line {number} is not a field")
        name = match[1].lower()
        if name not in KNOWN_FIELDS:
            raise SecurityTxtError(f"line {number}: unknown field {match[1]}")
        fields.setdefault(name, []).append(match[2])
    contacts = fields.get("contact", [])
    if not contacts:
        raise SecurityTxtError("no Contact")
    for contact in contacts:
        if not contact.startswith(("mailto:", "https://", "tel:")):
            raise SecurityTxtError("a Contact is not a mailto, https or tel URI")
    for name in ("canonical", "policy", "encryption"):
        for value in fields.get(name, []):
            if not value.startswith("https://"):
                raise SecurityTxtError(f"{name} is not an https URI")
    expires = fields.get("expires", [])
    if len(expires) != 1:
        raise SecurityTxtError("Expires must appear exactly once")
    try:
        when = datetime.fromisoformat(expires[0].replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecurityTxtError("Expires is not an RFC 3339 date-time") from exc
    if when.tzinfo is None:
        raise SecurityTxtError("Expires has no time zone")
    if when <= now:
        raise SecurityTxtError("Expires is in the past")
    if when - now > timedelta(days=365):
        raise SecurityTxtError("Expires is more than a year away")
    return fields


def site_handles(caddyfile: str) -> list[str]:
    """The first line of each top-level ``handle`` in the site block, in order."""
    site = caddyfile[caddyfile.index(f"{HOST} {{") :]
    handles: list[str] = []
    depth = 0
    for line in site.splitlines():
        stripped = line.strip()
        if depth == 1 and stripped.startswith("handle"):
            handles.append(stripped)
        depth += line.count("{") - line.count("}")
        if depth == 0 and handles:
            break
    return handles


# --- negative cases first ---------------------------------------------------------------

NOW = datetime(2026, 10, 25, tzinfo=UTC)
GOOD = "Contact: mailto:a@example.invalid\nExpires: 2027-10-01T00:00:00Z\n"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("Expires: 2027-10-01T00:00:00Z\n", "no Contact"),
        ("Contact: a@example.invalid\nExpires: 2027-10-01T00:00:00Z\n", "not a mailto"),
        ("Contact: mailto:a@example.invalid\n", "exactly once"),
        (GOOD + "Expires: 2027-09-01T00:00:00Z\n", "exactly once"),
        ("Contact: mailto:a@example.invalid\nExpires: 2026-10-01T00:00:00Z\n", "past"),
        ("Contact: mailto:a@example.invalid\nExpires: 2027-11-01T00:00:00Z\n", "a year"),
        ("Contact: mailto:a@example.invalid\nExpires: 1 Oct 2027\n", "RFC 3339"),
        ("Contact: mailto:a@example.invalid\nExpires: 2027-10-01T00:00:00\n", "time zone"),
        (GOOD + "Contacts: mailto:b@example.invalid\n", "unknown field"),
        (GOOD + "Policy: http://example.invalid/policy\n", "https"),
        (GOOD + "just text\n", "not a field"),
        (GOOD.rstrip("\n"), "line break"),
    ],
)
def test_a_malformed_security_txt_is_refused(text: str, error: str) -> None:
    with pytest.raises(SecurityTxtError, match=error):
        parse_security_txt(text, now=NOW)


def test_the_disclosure_page_loads_no_script_and_calls_no_api() -> None:
    html = DISCLOSURE.read_text(encoding="utf-8")
    assert "<script" not in html.lower()
    # The CSP allows 'self' only: no inline style, no third-party resource.
    assert "<style" not in html.lower() and " style=" not in html.lower()
    assert "/api/" not in html
    assert not re.search(r"""(src|href)=["']https?://""", html)


def test_the_trust_page_is_unpublished_by_default() -> None:
    caddyfile = CADDYFILE.read_text(encoding="utf-8")
    assert "import trust_page_{$ASKSPORE_TRUST_PAGE:unpublished}" in caddyfile
    unpublished = caddyfile[caddyfile.index("(trust_page_unpublished) {") :]
    assert unpublished.splitlines()[1].strip() == "respond 404"
    compose = yaml.safe_load((REPO / "infra" / "compose.dev.yml").read_text(encoding="utf-8"))
    env = compose["services"]["caddy"]["environment"]
    assert env["ASKSPORE_TRUST_PAGE"] == "${ASKSPORE_TRUST_PAGE:-unpublished}"
    # The draft is not in the build, so even a flipped flag has nothing to serve yet.
    assert not (PUBLIC / "trust.html").exists()


# --- the files ----------------------------------------------------------------------------


def test_security_txt_parses_and_expires_within_a_year() -> None:
    text = SECURITY_TXT.read_text(encoding="utf-8")
    fields = parse_security_txt(text, now=datetime.now(UTC))
    assert fields["policy"] == [f"https://{HOST}/security-disclosure"]
    assert fields["canonical"] == [f"https://{HOST}/.well-known/security.txt"]
    assert fields["preferred-languages"] == ["en"]


def test_security_txt_matches_its_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    section = draft[draft.index("## security.txt") :]
    block = section[section.index("```\n") + 4 :]
    block = block[: block.index("```")]
    assert block == SECURITY_TXT.read_text(encoding="utf-8")


def test_the_disclosure_page_names_the_security_txt_contact() -> None:
    text = SECURITY_TXT.read_text(encoding="utf-8")
    contact = parse_security_txt(text, now=datetime.now(UTC))["contact"][0]
    assert f'href="{contact}"' in DISCLOSURE.read_text(encoding="utf-8")


# --- the routes -----------------------------------------------------------------------------


def test_caddy_serves_the_public_files_before_the_app() -> None:
    handles = site_handles(CADDYFILE.read_text(encoding="utf-8"))
    names = [h.removesuffix("{").strip() for h in handles]
    app = names.index("handle")  # the web build with its index.html fallback
    for route in ("/.well-known/security.txt", "/security-disclosure", "/trust"):
        assert names.index(f"handle {route}") < app
    assert names.index("handle @public_page_files") < app
    assert names.index("handle @api") < names.index("handle /.well-known/security.txt")


def test_the_web_build_ships_the_public_files() -> None:
    dockerfile = (REPO / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY public ./public" in dockerfile
    dockerignore = (REPO / "apps" / "web" / ".dockerignore").read_text(encoding="utf-8")
    assert "public" not in dockerignore.split()


def test_the_dev_web_container_mounts_the_public_files() -> None:
    compose = yaml.safe_load((REPO / "infra" / "compose.dev.yml").read_text(encoding="utf-8"))
    assert "../apps/web/public:/srv/web/public:ro" in compose["services"]["web"]["volumes"]


def test_the_dev_server_mirrors_the_caddy_routes() -> None:
    vite = (REPO / "apps" / "web" / "vite.config.ts").read_text(encoding="utf-8")
    assert '"/security-disclosure": "/security-disclosure.html"' in vite
    for path in ("/security-disclosure.html", "/trust", "/trust.html"):
        assert f'"{path}"' in vite


def _caddy() -> str | None:
    return os.environ.get("CADDY_BIN") or shutil.which("caddy")


def _get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 (loopback)
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, "", b""


@pytest.mark.skipif(_caddy() is None, reason="no caddy binary (CADDY_BIN or PATH)")
@pytest.mark.parametrize("flag", [None, "published"])
def test_the_real_caddyfile_serves_the_public_routes(tmp_path: Path, flag: str | None) -> None:
    caddy = _caddy()
    assert caddy
    root = tmp_path / "web"
    shutil.copytree(PUBLIC, root)
    (root / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    local = (
        CADDYFILE.read_text(encoding="utf-8")
        .replace(f"{HOST} {{", f"http://127.0.0.1:{port} {{")
        .replace("/srv/web", str(root))
        .replace("reverse_proxy api:8000", 'respond "api" 299')
    )
    local = re.sub(r"^\temail .*\n", "", local, flags=re.MULTILINE)
    config = tmp_path / "Caddyfile"
    config.write_text(local, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "ASKSPORE_TRUST_PAGE"}
    if flag:
        env["ASKSPORE_TRUST_PAGE"] = flag
        (root / "trust.html").write_text("<p>synthetic trust page</p>", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        [caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
        env={**env, "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _get(base + "/")
                break
            except OSError:
                time.sleep(0.1)
        status, kind, body = _get(base + "/.well-known/security.txt")
        assert (status, kind) == (200, "text/plain; charset=utf-8")
        assert body == SECURITY_TXT.read_bytes()
        status, kind, body = _get(base + "/security-disclosure")
        assert status == 200 and kind.startswith("text/html")
        assert body == DISCLOSURE.read_bytes()
        assert _get(base + "/security-disclosure.html")[0] == 404
        assert _get(base + "/trust.html")[0] == 404
        assert _get(base + "/trust")[0] == (200 if flag else 404)
        assert _get(base + "/some/route")[2] == b"<div id=root></div>"
    finally:
        process.terminate()
        process.wait(timeout=10)
