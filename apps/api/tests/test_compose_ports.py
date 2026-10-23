"""P1c-04 (independent review, Oct 22, 2026): nothing is published beyond the loopback
except Caddy's 80 and 443.

Parses every Compose file under ``infra/`` (short and long port syntax, with
``${VAR:-default}`` interpolation resolved to its default) and fails on any published
port whose host address is not ``127.0.0.1``, other than the ``caddy`` service's 80 and
443. A port with no host address binds every interface, so it fails too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE_FILES = sorted(
    {
        *REPO.glob("infra/**/docker-compose*.yml"),
        *REPO.glob("infra/**/docker-compose*.yaml"),
        *REPO.glob("infra/**/compose*.yml"),
        *REPO.glob("infra/**/compose*.yaml"),
    }
)
PUBLIC = {("caddy", "80"), ("caddy", "443")}
LOOPBACK = "127.0.0.1"
_DEFAULT = re.compile(r"\$\{[A-Za-z0-9_]+(?::?-([^}]*))?\}")


def interpolate(value: str) -> str:
    return _DEFAULT.sub(lambda m: m.group(1) or "", value)


def published(entry: Any) -> tuple[str, str]:
    """(host address, host port) of one ``ports`` entry; address "" means every interface."""
    if isinstance(entry, dict):
        host_ip = interpolate(str(entry.get("host_ip", "")))
        port = interpolate(str(entry.get("published", entry.get("target", ""))))
        return host_ip, port
    spec = interpolate(str(entry)).split("/", 1)[0]
    if spec.startswith("["):  # [::1]:8080:80
        address, _, rest = spec[1:].partition("]:")
        return address, rest.split(":", 1)[0]
    parts = spec.split(":")
    if len(parts) == 3:
        return parts[0], parts[1]
    if len(parts) == 2:
        return "", parts[0]
    return "", parts[0]  # container port only: Docker picks a host port on every interface


def ports(path: Path) -> list[tuple[str, str, str]]:
    compose = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found = []
    for name, service in (compose.get("services") or {}).items():
        for entry in (service or {}).get("ports") or []:
            address, port = published(entry)
            found.append((name, address, port))
    return found


def offending(path: Path) -> list[tuple[str, str, str]]:
    return [
        (name, address, port)
        for name, address, port in ports(path)
        if address != LOOPBACK and (name, port) not in PUBLIC
    ]


def test_the_compose_files_are_found() -> None:
    names = {p.relative_to(REPO).as_posix() for p in COMPOSE_FILES}
    assert {
        "infra/compose.dev.yml",
        "infra/ragflow/docker-compose.yml",
        "infra/authentik/docker-compose.yml",
    } <= names


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.relative_to(REPO).as_posix())
def test_nothing_is_published_beyond_the_loopback_but_caddy(path: Path) -> None:
    assert offending(path) == []


def test_caddy_publishes_80_and_443_only() -> None:
    caddy = [
        (address, port)
        for name, address, port in ports(REPO / "infra" / "compose.dev.yml")
        if name == "caddy"
    ]
    assert {port for _, port in caddy} == {"80", "443"}


@pytest.mark.parametrize(
    ("entry", "bad"),
    [
        ("5432:5432", True),
        ("0.0.0.0:6379:6379", True),
        ("${API_PORT:-8000}:8000", True),
        ("8000", True),
        ({"target": 9000, "published": 9000}, True),
        ({"target": 9000, "published": 9000, "host_ip": "0.0.0.0"}, True),  # noqa: S104
        ("[::]:8080:80", True),
        ("127.0.0.1:${POSTGRES_PORT:-5432}:5432", False),
        ({"target": 9000, "published": "9000", "host_ip": "127.0.0.1"}, False),
    ],
)
def test_the_check_catches_every_way_to_publish_a_port(
    tmp_path: Path, entry: Any, bad: bool
) -> None:
    path = tmp_path / "compose.yml"
    path.write_text(yaml.safe_dump({"services": {"db": {"ports": [entry]}}}), encoding="utf-8")
    assert bool(offending(path)) is bad
    # Caddy's exemption is for 80 and 443 only.
    path.write_text(
        yaml.safe_dump({"services": {"caddy": {"ports": ["8443:8443", "443:443/udp"]}}}),
        encoding="utf-8",
    )
    assert offending(path) == [("caddy", "", "8443")]
