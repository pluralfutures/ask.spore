"""Drill only: generate the Keycloak drill's secrets and realm file outside the repository.

Writes, root only, under /srv/ask-spore/drills/:
- keycloak.env: the Keycloak bootstrap admin (the container's env_file);
- realm/ask-spore-drill.json: the realm, client secret and test users' passwords filled in;
- owner.txt: what the owner needs (client ID, client secret, issuer, the two users).
Prints file names only, never a value. Refuses to overwrite an existing file.

    python3 infra/drills/keycloak/setup.py --source-slug sso-<tenant> \
        --verified-email A --outsider-email B

The source slug is the one the operator console gives the tenant's SSO source
(`sso-<tenant slug>`); the client's redirect URI is built from it.
"""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path
from string import Template

OUT = Path("/srv/ask-spore/drills")
KEYCLOAK_UID = 1000  # the image's user


def write(path: Path, text: str, *, uid: int = 0) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chown(path, uid, 0)
    sys.stdout.write(f"wrote {path}\n")


def source_slug(value: str) -> str:
    """The SSO source slug in the client's redirect URI (Phase 1c release: `sso-ssotest2`)."""
    if not re.fullmatch(r"sso-[a-z0-9][a-z0-9-]{0,62}", value):
        raise argparse.ArgumentTypeError("expected sso-<tenant slug>")
    return value


def realm_values(slug: str, verified_email: str, outsider_email: str) -> dict[str, str]:
    return {
        "DRILL_SOURCE_SLUG": slug,
        "DRILL_CLIENT_SECRET": secrets.token_urlsafe(32),
        "DRILL_VERIFIED_EMAIL": verified_email,
        "DRILL_VERIFIED_PASSWORD": secrets.token_urlsafe(18),
        "DRILL_OUTSIDER_EMAIL": outsider_email,
        "DRILL_OUTSIDER_PASSWORD": secrets.token_urlsafe(18),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-slug", required=True, type=source_slug)
    parser.add_argument("--verified-email", required=True)
    parser.add_argument("--outsider-email", required=True)
    args = parser.parse_args()
    values = realm_values(args.source_slug, args.verified_email, args.outsider_email)
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    realm_dir = OUT / "realm"
    realm_dir.mkdir(mode=0o700, exist_ok=True)
    os.chown(realm_dir, KEYCLOAK_UID, 0)
    template = Template((Path(__file__).parent / "realm.template.json").read_text("utf-8"))
    write(realm_dir / "ask-spore-drill.json", template.substitute(values), uid=KEYCLOAK_UID)
    write(
        OUT / "keycloak.env",
        f"KC_BOOTSTRAP_ADMIN_USERNAME=drill-admin\n"
        f"KC_BOOTSTRAP_ADMIN_PASSWORD={secrets.token_urlsafe(24)}\n",
    )
    write(
        OUT / "owner.txt",
        "Generic OIDC drill (Keycloak)\n"
        "Issuer: https://idp-test.askspore.myceliumgastronomy.com/realms/ask-spore-drill\n"
        "Client ID: ask-spore-drill\n"
        f"Client secret: {values['DRILL_CLIENT_SECRET']}\n"
        f"Verified-domain user: {args.verified_email} / {values['DRILL_VERIFIED_PASSWORD']}\n"
        f"Unverified-domain user: {args.outsider_email} / {values['DRILL_OUTSIDER_PASSWORD']}\n",
    )


if __name__ == "__main__":
    main()
