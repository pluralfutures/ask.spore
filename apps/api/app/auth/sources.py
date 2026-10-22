"""A tenant's SSO source, as the operator configures it (P1b-07).

The operator console's login-policy page sets one source per tenant: Microsoft Entra
ID, Google Workspace, a generic OIDC provider or a SAML 2.0 IdP (from its metadata).
This module turns the operator's fields into the non-secret configuration we store in
``tenant_login_policy.sso_source_config`` and the ``SourceSpec`` Authentik is given
(``app.auth.authentik``). Client secrets are passed through to Authentik and never
stored or logged here; SAML signing keys are generated in Authentik and never leave it.

The redirect URIs the client's IT registers at their IdP are on our public host
(``[auth.authentik] public_url``), under the paths Authentik uses: Caddy hands them to
the API (``infra/caddy/Caddyfile``), which completes the sign-in against Authentik on
the Compose network, so the browser never talks to Authentik (P1a-02).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID
from xml.etree import ElementTree

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from app.auth.provider import SourceSpec
from app.tenancy.login_policy import SsoKind

MAX_METADATA_BYTES: Final = 256 * 1024
SAML_REDIRECT_BINDING: Final = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
_MD: Final = "{urn:oasis:names:tc:SAML:2.0:metadata}"
_DS: Final = "{http://www.w3.org/2000/09/xmldsig#}"
# No document type, so no entity can be declared or expanded (billion laughs, XXE).
_FORBIDDEN_XML = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
# Authentik's paths for a source's callback (OAuth) and assertion consumer (SAML).
OAUTH_CALLBACK_PATH: Final = "/source/oauth/callback/{slug}/"
SAML_ACS_PATH: Final = "/source/saml/{slug}/acs/"
SAML_METADATA_PATH: Final = "/source/saml/{slug}/metadata/"


class SourceRefused(ValueError):
    """The operator's source fields cannot be used; ``error_code`` says why."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class IdpMetadata:
    entity_id: str
    sso_url: str
    certificate_pem: str
    certificate_sha256: str
    certificate_not_after: str  # ISO date


def source_slug(tenant_slug: str) -> str:
    """The Authentik source's slug for a tenant: stable across kind changes."""
    return f"sso-{tenant_slug}"


def public_https_url(raw: str, *, error_code: str) -> str:
    """An ``https`` URL on a public DNS name (no credentials, no IP literal, no port)."""
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or not _HOSTNAME.fullmatch(host)
    ):
        raise SourceRefused(error_code)
    return raw.strip()


def entra_config(
    entra_tenant_id: UUID, client_id: str, admin_group_ids: list[UUID]
) -> dict[str, str | list[str]]:
    return {
        "entra_tenant_id": str(entra_tenant_id),
        "client_id": client_id.strip(),
        "admin_group_ids": sorted({str(g) for g in admin_group_ids}),
    }


def google_config(client_id: str) -> dict[str, str | list[str]]:
    return {"client_id": client_id.strip()}


def oidc_config(issuer: str, client_id: str) -> dict[str, str | list[str]]:
    return {
        "issuer": public_https_url(issuer, error_code="invalid_issuer").rstrip("/"),
        "client_id": client_id.strip(),
    }


def saml_config(metadata: IdpMetadata) -> dict[str, str | list[str]]:
    return {
        "idp_entity_id": metadata.entity_id,
        "sso_url": metadata.sso_url,
        "certificate_sha256": metadata.certificate_sha256,
        "certificate_not_after": metadata.certificate_not_after,
    }


def config_digest(kind: SsoKind | None, config: dict[str, str | list[str]]) -> str | None:
    """A fingerprint of the stored configuration, for the audit trail."""
    if kind is None:
        return None
    canonical = json.dumps({"kind": kind, **config}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def spec_for(
    *,
    tenant_id: UUID,
    tenant_slug: str,
    verified_domains: list[str],
    kind: SsoKind,
    config: dict[str, str | list[str]],
    certificate_pem: str | None = None,
) -> SourceSpec:
    if not verified_domains:
        # Sign-ins are accepted only for verified domains: without one, nobody could.
        raise SourceRefused("no_verified_domains")
    return SourceSpec(
        tenant_id=tenant_id,
        slug=source_slug(tenant_slug),
        name=f"ask.spore {tenant_slug}",
        kind=kind,
        verified_domains=tuple(sorted(verified_domains)),
        config=config,
        certificate_pem=certificate_pem,
    )


def endpoints(public_url: str, kind: SsoKind, slug: str) -> dict[str, str]:
    """What the client's IT registers at their IdP for this source."""
    base = public_url.rstrip("/")
    if kind == "saml":
        return {
            "acs_url": base + SAML_ACS_PATH.format(slug=slug),
            "sp_entity_id": base + SAML_METADATA_PATH.format(slug=slug),
        }
    return {"redirect_uri": base + OAUTH_CALLBACK_PATH.format(slug=slug)}


# --- SAML IdP metadata ----------------------------------------------------------------


def parse_idp_metadata(xml: str) -> IdpMetadata:
    """The entity ID, HTTP-Redirect SSO URL and signing certificate of one SAML IdP.

    Refuses a document type (so no entity declarations), more than 256 KB, more or
    fewer than one IdP, an SSO URL that is not public ``https``, and a certificate that
    does not parse.
    """
    if len(xml.encode("utf-8")) > MAX_METADATA_BYTES:
        raise SourceRefused("metadata_too_large")
    if _FORBIDDEN_XML.search(xml):
        raise SourceRefused("metadata_doctype")
    try:
        # No DTD can be present (checked above), so no entity is ever expanded.
        root = ElementTree.fromstring(xml)  # noqa: S314
    except ElementTree.ParseError:
        raise SourceRefused("metadata_unreadable") from None
    entities = [root] if root.tag == f"{_MD}EntityDescriptor" else []
    if root.tag == f"{_MD}EntitiesDescriptor":
        entities = root.findall(f"{_MD}EntityDescriptor")
    idps = [(e, d) for e in entities for d in e.findall(f"{_MD}IDPSSODescriptor")]
    if len(idps) != 1:
        raise SourceRefused("metadata_not_one_idp")
    entity, descriptor = idps[0]
    entity_id = (entity.get("entityID") or "").strip()
    if not entity_id or len(entity_id) > 1024:
        raise SourceRefused("metadata_no_entity_id")
    locations = [
        (service.get("Location") or "").strip()
        for service in descriptor.findall(f"{_MD}SingleSignOnService")
        if service.get("Binding") == SAML_REDIRECT_BINDING
    ]
    if not locations or not locations[0]:
        # Authentik sends the request with the Redirect binding; POST would need a page
        # in the browser that talks to Authentik.
        raise SourceRefused("metadata_no_redirect_binding")
    sso_url = public_https_url(locations[0], error_code="metadata_bad_sso_url")
    certificates = [
        key.find(f"{_DS}KeyInfo/{_DS}X509Data/{_DS}X509Certificate")
        for key in descriptor.findall(f"{_MD}KeyDescriptor")
        if key.get("use") in (None, "signing")
    ]
    texts = [c.text for c in certificates if c is not None and c.text]
    if not texts:
        raise SourceRefused("metadata_no_certificate")
    try:
        der = base64.b64decode("".join(texts[0].split()), validate=True)
        certificate = x509.load_der_x509_certificate(der)
    except (binascii.Error, ValueError):
        raise SourceRefused("metadata_bad_certificate") from None
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return IdpMetadata(
        entity_id=entity_id,
        sso_url=sso_url,
        certificate_pem=pem,
        certificate_sha256=hashlib.sha256(der).hexdigest(),
        certificate_not_after=certificate.not_valid_after_utc.astimezone(UTC).date().isoformat(),
    )
