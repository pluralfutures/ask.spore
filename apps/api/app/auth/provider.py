"""The identity provider behind sign-in links, as the API sees it (P1a-02).

Authentik and the transactional email provider are external services. The API
talks to them only through ``SignInLinkProvider``: ``app.auth.authentik`` is the
real implementation (Authentik's flow executor and OIDC endpoints; Authentik's
email stage sends the link over the configured SMTP relay, Scaleway Transactional
Email), and the tests use an in-memory fake (``tests/fake_idp.py``).

The controls the compliance guide requires of sign-in links do not depend on the
provider: browser binding, one POST per link, expiry and no enumeration are enforced
by ``app.auth.links`` before the provider is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class LinkRefused(Exception):
    """The provider would not redeem the link token (unknown, expired or already used)."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class ProviderError(Exception):
    """The provider could not be reached or answered something unexpected."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str


class SignInLinkProvider(Protocol):
    async def send_sign_in_link(self, email: str) -> None:
        """Email ``email`` a single-use link to the landing page (token in the fragment)."""
        ...

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens:
        """Complete the sign-in flow with ``token``; raise LinkRefused if it is not valid."""
        ...

    async def provision_user(self, *, email: str, display_name: str, tenant_id: UUID) -> None:
        """Create or update the provider's user, carrying ``tenant_id`` into its tokens."""
        ...

    async def revoke_token(self, access_token: str) -> None:
        """Revoke an access token at the provider on sign-out (P1a-02, best effort)."""
        ...

    async def aclose(self) -> None: ...
