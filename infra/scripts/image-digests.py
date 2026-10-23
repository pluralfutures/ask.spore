#!/usr/bin/env python3
"""Print (or pin) the registry digests of every container image the repository uses.

P1b-15 g, architecture §8 "Hardening": images are pinned by digest as well as by tag
(``name:tag@sha256:...``), so a re-pushed tag cannot change what runs. The tag stays
for readers; the digest decides what is pulled.

    python3 infra/scripts/image-digests.py            # print ref -> current digest
    python3 infra/scripts/image-digests.py --check    # exit 1 if a pinned digest moved
    python3 infra/scripts/image-digests.py --write    # pin (or re-pin) every reference

Scans infra/**/docker-compose*.yml, infra/compose*.yml, apps/*/Dockerfile* and
.github/workflows/*.yml. Asks Docker Hub and ghcr.io anonymously (registry API v2,
a HEAD of the manifest list, so the digest covers every platform). Standard library
only; honours HTTPS_PROXY and SSL_CERT_FILE. To upgrade an image: change its tag, run
--write, review and commit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = (
    "infra/**/docker-compose*.yml",
    "infra/compose*.yml",
    "infra/drills/**/compose*.yml",
    "apps/*/Dockerfile*",
    ".github/workflows/*.yml",
)
# "image: <ref>" in Compose and workflow services, "FROM <ref>" in Dockerfiles.
REF = re.compile(
    r"(?P<lead>^\s*(?:image:\s*|FROM\s+))"
    r"(?P<name>[a-z0-9][a-z0-9._/-]*):(?P<tag>[A-Za-z0-9._-]+)"
    r"(?:@(?P<digest>sha256:[0-9a-f]{64}))?",
    re.MULTILINE,
)
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def registry_repo(name: str) -> tuple[str, str]:
    """(registry host, repository) for an image name."""
    parts = name.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0]):
        host, repo = parts[0], "/".join(parts[1:])
    else:
        host, repo = "registry-1.docker.io", name
    if host in ("docker.io", "registry-1.docker.io"):
        host = "registry-1.docker.io"
        if "/" not in repo:
            repo = f"library/{repo}"
    return host, repo


def _token(host: str, repo: str) -> str:
    if host == "registry-1.docker.io":
        url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
    elif host == "ghcr.io":
        url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    else:
        return ""
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed hosts
        data = json.load(response)
    return str(data.get("token") or data.get("access_token") or "")


HUB_MIRROR = ""  # set by --hub-mirror


def digest(name: str, tag: str) -> str:
    host, repo = registry_repo(name)
    if host == "registry-1.docker.io" and HUB_MIRROR:
        host = HUB_MIRROR  # anonymous, v2 API, same content-addressed digests
    request = urllib.request.Request(  # noqa: S310 - registry hosts from the image names
        f"https://{host}/v2/{repo}/manifests/{tag}", method="HEAD", headers={"Accept": ACCEPT}
    )
    token = _token(host, repo)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        found = response.headers.get("Docker-Content-Digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", found):
        raise RuntimeError(f"{name}:{tag}: no digest in the registry's answer")
    return found


def files() -> list[Path]:
    return sorted({p for pattern in PATTERNS for p in ROOT.glob(pattern) if p.is_file()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if a pin differs")
    mode.add_argument("--write", action="store_true", help="pin every reference in place")
    parser.add_argument(
        "--hub-mirror",
        metavar="HOST",
        help="ask this Docker Hub mirror (e.g. mirror.gcr.io) instead of Docker Hub, whose "
        "anonymous limit is 100 manifest requests an hour per address; digests are content "
        "hashes, so they are the same, but a mirror may lag a re-pushed tag: --check against "
        "Docker Hub itself before relying on a changed one",
    )
    args = parser.parse_args(argv)
    global HUB_MIRROR
    HUB_MIRROR = args.hub_mirror or ""
    cache: dict[tuple[str, str], str] = {}
    moved = 0
    for path in files():
        text = path.read_text(encoding="utf-8")

        def pin(match: re.Match[str], path: Path = path) -> str:
            nonlocal moved
            key = (match["name"], match["tag"])
            if key not in cache:
                cache[key] = digest(*key)
            current = cache[key]
            pinned = match["digest"]
            rel = path.relative_to(ROOT)
            state = "pinned" if pinned == current else ("MOVED" if pinned else "unpinned")
            if pinned and pinned != current:
                moved += 1
            sys.stdout.write(f"{rel}: {key[0]}:{key[1]}@{current} ({state})\n")
            return f"{match['lead']}{key[0]}:{key[1]}@{current}"

        updated = REF.sub(pin, text)
        if args.write and updated != text:
            path.write_text(updated, encoding="utf-8")
    if args.check and moved:
        sys.stderr.write(f"{moved} pinned digest(s) no longer match their tag\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
