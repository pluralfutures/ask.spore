"""P1b-07: reading a SAML IdP's metadata, and the source mapping Authentik runs.

Synthetic metadata with a throwaway self-signed certificate. The mapping expression
generated for a tenant's source is run here as Authentik runs a property mapping (the
expression as a function body, with the variables Authentik passes), so its domain and
``hd`` checks and the attributes it sets are tested without an Authentik instance.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.auth.authentik import mapping_expression
from app.auth.sources import (
    SourceRefused,
    entra_config,
    google_config,
    oidc_config,
    parse_idp_metadata,
    public_https_url,
    saml_config,
    spec_for,
)

REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
TENANT = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


def certificate_b64() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.synthetic.example")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")


def metadata_xml(
    *,
    bindings: tuple[str, ...] = (REDIRECT, POST),
    location: str = "https://idp.synthetic.example/sso",
    idps: int = 1,
    certificate: str | None = None,
    prolog: str = "",
) -> str:
    cert = certificate if certificate is not None else certificate_b64()
    services = "".join(
        f'<md:SingleSignOnService Binding="{b}" Location="{location}"/>' for b in bindings
    )
    descriptor = (
        '<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>'
        f"<ds:X509Certificate>\n{cert}\n</ds:X509Certificate>"
        "</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"
        f"{services}</md:IDPSSODescriptor>"
    )
    return (
        f"{prolog}"
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
        'entityID="https://idp.synthetic.example/metadata">'
        f"{descriptor * idps}</md:EntityDescriptor>"
    )


# --- metadata ---------------------------------------------------------------------------


def test_reads_entity_redirect_url_and_certificate() -> None:
    parsed = parse_idp_metadata(metadata_xml().replace("\n", "\r\n").replace("\r\n", "\n"))
    assert parsed.entity_id == "https://idp.synthetic.example/metadata"
    assert parsed.sso_url == "https://idp.synthetic.example/sso"
    assert parsed.certificate_pem.startswith("-----BEGIN CERTIFICATE-----")
    assert len(parsed.certificate_sha256) == 64
    config = saml_config(parsed)
    assert set(config) == {
        "idp_entity_id",
        "sso_url",
        "certificate_sha256",
        "certificate_not_after",
    }
    assert "BEGIN" not in str(config)  # the certificate itself goes to Authentik only


@pytest.mark.parametrize(
    ("xml", "code"),
    [
        (
            metadata_xml(prolog='<!DOCTYPE x [<!ENTITY a "aaaa">]>'),
            "metadata_doctype",
        ),
        (metadata_xml(prolog="<!doctype x>"), "metadata_doctype"),
        (metadata_xml(bindings=(POST,)), "metadata_no_redirect_binding"),
        (metadata_xml(location="http://idp.synthetic.example/sso"), "metadata_bad_sso_url"),
        (metadata_xml(location="https://10.0.0.5/sso"), "metadata_bad_sso_url"),
        (metadata_xml(idps=2), "metadata_not_one_idp"),
        (metadata_xml(certificate="bm90IGEgY2VydA=="), "metadata_bad_certificate"),
        (metadata_xml(certificate="%%%"), "metadata_bad_certificate"),
        ("<md:EntityDescriptor", "metadata_unreadable"),
        ("x" * (256 * 1024 + 1), "metadata_too_large"),
    ],
)
def test_refuses_unusable_metadata(xml: str, code: str) -> None:
    with pytest.raises(SourceRefused) as refused:
        parse_idp_metadata(xml)
    assert refused.value.error_code == code


@pytest.mark.parametrize(
    "url",
    [
        "http://idp.example/x",
        "https://user:pw@idp.example/x",
        "https://idp.example:8443/x",
        "https://localhost/x",
        "https://authentik-server/x",
        "https://192.168.1.1/x",
    ],
)
def test_issuer_must_be_public_https(url: str) -> None:
    with pytest.raises(SourceRefused):
        public_https_url(url, error_code="invalid_issuer")


def test_a_source_needs_a_verified_domain() -> None:
    with pytest.raises(SourceRefused, match="no_verified_domains"):
        spec_for(
            tenant_id=TENANT,
            tenant_slug="cc",
            verified_domains=[],
            kind="google",
            config=google_config("x"),
        )


# --- the source mapping, run as Authentik runs it ---------------------------------------


def run_mapping(kind: str, config: dict[str, Any], **variables: Any) -> dict[str, Any]:
    spec = spec_for(
        tenant_id=TENANT,
        tenant_slug="cc",
        verified_domains=["client.example", "client-two.example"],
        kind=kind,  # type: ignore[arg-type]
        config=config,
    )
    body = "\n".join("    " + line for line in mapping_expression(spec).splitlines())
    namespace: dict[str, Any] = {}
    exec(f"def handler(info, properties, name_id, source):\n{body}", namespace)  # noqa: S102
    defaults = {"info": {}, "properties": {}, "name_id": None, "source": None}
    result: dict[str, Any] = namespace["handler"](**{**defaults, **variables})
    return result


def test_mapping_stamps_the_sources_tenant_never_a_claim() -> None:
    out = run_mapping(
        "oidc",
        oidc_config("https://idp.client.example", "c"),
        info={
            "email": "Someone@Client.example",
            "email_verified": True,
            "ask_spore_tenant": str(uuid.uuid4()),  # a claim of the IdP's: ignored
        },
    )
    assert out["email"] == "someone@client.example"
    assert out["username"] == "sso-cc.someone@client.example"
    assert out["path"] == "ask-spore/sso"
    assert out["attributes"]["ask_spore_tenant"] == str(TENANT)
    assert out["attributes"]["ask_spore_sso"] == {
        "source": "sso-cc",
        "hd": "",
        "email_verified": True,
        "admin": False,
    }


def test_mapping_refuses_an_unverified_domain() -> None:
    with pytest.raises(ValueError, match="domain_not_verified"):
        run_mapping("entra", entra_config(TENANT, "c", []), info={"mail": "x@other.example"})


@pytest.mark.parametrize("hd", ["", "other.example"])
def test_mapping_refuses_a_google_hd_mismatch(hd: str) -> None:
    with pytest.raises(ValueError, match="hd_mismatch"):
        run_mapping(
            "google",
            google_config("c"),
            info={"email": "x@client.example", "hd": hd, "verified_email": True},
        )


def test_mapping_google_and_entra_groups() -> None:
    google = run_mapping(
        "google",
        google_config("c"),
        info={"email": "x@client-two.example", "hd": "client-two.example", "verified_email": True},
    )
    assert google["attributes"]["ask_spore_sso"]["hd"] == "client-two.example"
    assert google["attributes"]["ask_spore_sso"]["email_verified"] is True
    group = uuid.uuid4()
    entra = run_mapping(
        "entra",
        entra_config(TENANT, "c", [group]),
        info={"mail": "x@client.example"},
        properties={"groups": [str(group), "other"]},
    )
    assert entra["attributes"]["ask_spore_sso"]["admin"] is True
    assert entra["attributes"]["ask_spore_sso"]["email_verified"] is True  # tenant pinned


def test_mapping_saml_reads_the_name_id() -> None:
    class NameId:
        text = "X@client.example"

    out = run_mapping("saml", saml_config(parse_idp_metadata(metadata_xml())), name_id=NameId())
    assert out["email"] == "x@client.example"
    assert out["attributes"]["ask_spore_tenant"] == str(TENANT)
