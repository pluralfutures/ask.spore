#!/usr/bin/env python3
"""Refuse a host whose credentials are still the repository's published values (P1c-03).

The API refuses to start in OIDC mode when a secret it reads equals a published value
(``app.core.credentials``). This script makes the same check on the host's ``.env``
files, including the services the API never sees:

    .env                    (API, worker, migrations: the containers' env_file)
    infra/.env              (Compose interpolation, with the shell's environment:
                             POSTGRES_PASSWORD and APP_DB_PASSWORD of the Postgres roles)
    infra/authentik/.env    (Authentik's database password and secret key, bootstrap)
    infra/ragflow/.env      (Elasticsearch, MySQL, MinIO and Redis of RAGFlow)

A key fails when its value equals a non-empty value of its ``.env.example``, when it or
its URL password is any password the repository publishes (the examples, the Compose
``${VAR:-default}`` defaults, the CI workflow), or when it is unset and Compose would
fall back to a published default (``infra/compose.dev.yml``'s project directory is
``infra/``, so its ``${VAR:-default}`` values come from the shell or ``infra/.env``,
never from the root ``.env``). ``AUTHENTIK_BOOTSTRAP_*`` keys fail while present:
Authentik re-creates the bootstrap token from them at every start.

    python3 infra/scripts/check-credentials.py          # exit 1 and the key names if any fail

Prints key names only, never a value. Standard library only. Rotation:
``infra/README.md``, "Credentials rotation".
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = (".env", "infra/authentik/.env", "infra/ragflow/.env")
INTERPOLATION_FILE = "infra/.env"
COMPOSE_FILES = ("infra/compose.dev.yml", "infra/authentik/docker-compose.yml")
CI_FILES = (".github/workflows/ci.yml",)
SECRET_NAME = re.compile(r"(PASSWORD|SECRET|TOKEN|_KEY|_URL)$")
COMPOSE_DEFAULT = re.compile(r"\$\{([A-Z0-9_]+):-([^}]*)\}")
CI_PASSWORD = re.compile(r"PASSWORD:\s*([^\s#]+)|://[^:/@\s]+:([^@\s/]+)@")
BOOTSTRAP = re.compile(r"^AUTHENTIK_BOOTSTRAP_")


def parse_env(path: Path) -> dict[str, str]:
    """KEY=value lines of a dotenv file (comments and blank lines skipped)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def url_password(value: str) -> str | None:
    if "://" not in value:
        return None
    try:
        password = urlsplit(value).password
    except ValueError:
        return None
    return unquote(password) if password else None


def published(root: Path) -> tuple[set[str], dict[str, str]]:
    """Every password the repository publishes, and the Compose defaults of secrets."""
    values: set[str] = set()
    for name in ENV_FILES:
        for key, value in parse_env(root / f"{name}.example").items():
            if value and SECRET_NAME.search(key):
                values.add(url_password(value) or value if "_URL" in key else value)
    defaults: dict[str, str] = {}
    for name in COMPOSE_FILES:
        path = root / name
        if path.is_file():
            for key, value in COMPOSE_DEFAULT.findall(path.read_text(encoding="utf-8")):
                if value and SECRET_NAME.search(key):
                    defaults[key] = value
                    values.add(value)
    for name in CI_FILES:
        path = root / name
        if path.is_file():
            for match in CI_PASSWORD.findall(path.read_text(encoding="utf-8")):
                values.update(match)
    values.discard("")
    # URLs without a password publish no secret (REDIS_URL's example).
    return {v for v in values if "://" not in v}, defaults


def failing_keys(root: Path, environ: dict[str, str] | None = None) -> list[str]:
    values, defaults = published(root)
    shell = dict(os.environ if environ is None else environ)
    interpolation = {**parse_env(root / INTERPOLATION_FILE), **shell}
    failing: list[str] = []
    for key in sorted(defaults):
        # Compose falls back to a published default for an unset password.
        value = interpolation.get(key, "").strip()
        if not value:
            failing.append(f"{INTERPOLATION_FILE}:{key} (unset: Compose default)")
        elif value in values:
            failing.append(f"{INTERPOLATION_FILE}:{key}")
    for name in ENV_FILES:
        env = parse_env(root / name)
        example = parse_env(root / f"{name}.example")
        for key, value in env.items():
            if BOOTSTRAP.match(key):
                failing.append(f"{name}:{key} (bootstrap)")
                continue
            if not value or not SECRET_NAME.search(key):
                continue
            if "://" in value:
                # A URL fails on its password only (REDIS_URL's example has none).
                if url_password(value) in values:
                    failing.append(f"{name}:{key}")
            elif value == example.get(key) or value in values:
                failing.append(f"{name}:{key}")
    return failing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: here)")
    args = parser.parse_args(argv)
    missing = [name for name in ENV_FILES if not (args.root / name).is_file()]
    failing = failing_keys(args.root)
    for name in missing:
        print(f"note: {name} not found; its services cannot start without it")
    if failing:
        print("credentials still at a published value (rotate them, infra/README.md):")
        for key in failing:
            print(f"  {key}")
        return 1
    print(f"ok: no published credential in {', '.join(n for n in ENV_FILES if n not in missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
