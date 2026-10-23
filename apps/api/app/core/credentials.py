"""Refuse to start with a credential published in the repository (P1c-03).

The ``.env.example`` files, the Compose defaults and the CI workflow publish passwords
for local stacks (``askspore-dev``, ``askspore-app-dev``, RAGFlow's ``change-me``, CI's
database password). A deployment that still uses one of them is reachable with a
password anyone with the repository knows, so in ``[auth] mode = "oidc"`` (any
deployment real users sign in to) ``load_settings`` refuses to start when a secret the
process reads equals one of them: the whole value, or the password of a URL.

Only key names are reported; values are compared, never printed or logged.
``tests/test_credentials.py`` keeps ``PUBLISHED_VALUES`` equal to what the repository
publishes. ``infra/scripts/check-credentials.py`` makes the same check on the host's
``.env`` files, including the services the API never sees (RAGFlow, Authentik).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from urllib.parse import unquote, urlsplit

# Every non-empty secret value the repository publishes for local and CI stacks.
PUBLISHED_VALUES: Final[frozenset[str]] = frozenset(
    {"askspore-dev", "askspore-app-dev", "change-me", "ci-only-password"}
)

# The environment variables the API, the worker and the CLI read that hold a secret or
# a URL that may carry one. MIGRATIONS_DATABASE_URL reaches the API through the root
# .env (env_file) and is the CLI's owner connection.
CHECKED_KEYS: Final[tuple[str, ...]] = (
    "DATABASE_URL",
    "MIGRATIONS_DATABASE_URL",
    "REDIS_URL",
    "RAGFLOW_API_KEY",
    "AUTHENTIK_CLIENT_SECRET",
    "AUTHENTIK_API_TOKEN",
    "PHASE0_BEARER_TOKEN",
    "MISTRAL_API_KEY",
    "SCALEWAY_API_KEY",
    "OPENROUTER_API_KEY",
    "SCALEWAY_TEM_API_KEY",
    "MAILGUN_API_KEY",
)


def url_password(value: str) -> str | None:
    """The password of a ``scheme://user:password@host`` URL, if it has one."""
    if "://" not in value:
        return None
    try:
        password = urlsplit(value).password
    except ValueError:
        return None
    return unquote(password) if password else None


def is_published(value: str, published: frozenset[str] = PUBLISHED_VALUES) -> bool:
    value = value.strip()
    return bool(value) and (value in published or url_password(value) in published)


def published_credentials(
    env: Mapping[str, str], keys: tuple[str, ...] = CHECKED_KEYS
) -> list[str]:
    """Names of the ``keys`` whose value (or URL password) the repository publishes."""
    return [key for key in keys if is_published(env.get(key, ""))]
