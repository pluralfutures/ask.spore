"""The eval harness's service identity under ``[auth] mode = "oidc"`` (P1b-15 a).

Eval set v1 runs through the live API (packages/eval, the full pipeline), which in
Phase 1a needed ``mode = "phase0"`` and its shared bearer token (findings 1a A11, G7).
This path keeps ``mode = "oidc"`` and adds a **signed service credential**:

- the harness holds an Ed25519 private key (``EVAL_SERVICE_PRIVATE_KEY``, on the eval
  runner only) and signs a short-lived JWT for one internal-tenant user, the service
  identity (``ask-spore eval-identity create``: role ``user``, no operator or content
  role, never provisioned in Authentik, so it cannot sign in any other way);
- the API holds only the **public** key, in ``[auth.eval_service]``. Without that
  section (the repository's production config has none) no eval credential is
  accepted; with it, a token whose header names ``kid = "ask-spore-eval"`` is checked
  here instead of against Authentik: EdDSA signature, issuer, audience, expiry, a
  lifetime of at most ``max_lifetime_seconds``, and a subject equal to the configured
  email. The user is then resolved in the internal tenant only, like any request.
  Sign-out does not list it in ``revoked_sessions`` (that path checks Authentik's
  tokens); a credential lives at most ``max_lifetime_seconds`` (15 minutes by default).

Nothing here is a bearer secret in the API's configuration: a leak of the API's
configuration cannot mint a credential. No token or claim is logged.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Final

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from app.auth.tokens import MAX_TOKEN_LENGTH, Identity, InvalidToken
from app.tenancy.models import INTERNAL_TENANT_ID

KEY_ID: Final = "ask-spore-eval"
ISSUER: Final = "ask-spore-eval-harness"
AUDIENCE: Final = "ask-spore-eval"
DEFAULT_LIFETIME_SECONDS: Final = 600
LEEWAY_SECONDS: Final = 30


def load_public_key(pem: str) -> Ed25519PublicKey:
    """The configured public key; ValueError unless it is an Ed25519 public key."""
    key = load_pem_public_key(pem.strip().encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("the eval service key must be an Ed25519 public key")
    return key


def generate_key_pair() -> tuple[str, str]:
    """A new (private PEM, public PEM) pair: the private one for the eval runner's
    secret, the public one for ``[auth.eval_service] public_key``."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    public = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return private, public.decode()


def sign_credential(
    private_key_pem: str,
    email: str,
    *,
    lifetime_seconds: int = DEFAULT_LIFETIME_SECONDS,
    now: float | None = None,
) -> str:
    """A credential for the service identity ``email`` (the eval harness signs these)."""
    key = load_pem_private_key(private_key_pem.strip().encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("the eval service key must be an Ed25519 private key")
    issued = int(time.time() if now is None else now)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": email.strip().lower(),
        "iat": issued,
        "exp": issued + lifetime_seconds,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": KEY_ID})


def is_eval_credential(token: str) -> bool:
    """Whether the token's (unverified) header names the eval key; nothing is trusted
    from it beyond choosing which validator checks the token."""
    if len(token) > MAX_TOKEN_LENGTH:
        return False
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return False
    return header.get("kid") == KEY_ID


class EvalServiceValidator:
    def __init__(self, public_key_pem: str, email: str, max_lifetime_seconds: int) -> None:
        self._key = load_public_key(public_key_pem)
        self._email = email.strip().lower()
        self._max_lifetime = max_lifetime_seconds

    def validate(self, token: str) -> Identity:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["EdDSA"],
                audience=AUDIENCE,
                issuer=ISSUER,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError:
            raise InvalidToken("token_expired") from None
        except jwt.PyJWTError:
            raise InvalidToken("invalid_token") from None
        if claims["exp"] - claims["iat"] > self._max_lifetime:
            raise InvalidToken("lifetime_too_long")
        if claims["iat"] > time.time() + LEEWAY_SECONDS:
            raise InvalidToken("issued_in_future")
        if claims["sub"] != self._email:
            raise InvalidToken("unknown_service_identity")
        return Identity(
            subject=f"eval-service:{claims['sub']}",
            email=self._email,
            tenant_id=INTERNAL_TENANT_ID,
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
            service=True,
        )
