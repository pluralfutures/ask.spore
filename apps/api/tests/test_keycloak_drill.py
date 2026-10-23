"""The Keycloak drill's realm file (infra/drills/keycloak, Phase 1c release F3).

The client's redirect URI follows the SSO source slug passed to ``setup.py``, so the drill
works for whichever test tenant the release uses; synthetic addresses only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from string import Template
from types import ModuleType

import pytest

DRILL = Path(__file__).resolve().parents[3] / "infra" / "drills" / "keycloak"


def setup() -> ModuleType:
    spec = importlib.util.spec_from_file_location("keycloak_drill_setup", DRILL / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["keycloak_drill_setup"] = module
    spec.loader.exec_module(module)
    return module


def test_the_redirect_uri_follows_the_source_slug() -> None:
    drill = setup()
    values = drill.realm_values("sso-ssotest2", "a@verified.example", "b@other.example")
    realm = json.loads(
        Template((DRILL / "realm.template.json").read_text("utf-8")).substitute(values)
    )
    uris = [uri for client in realm["clients"] for uri in client.get("redirectUris", [])]
    assert uris == ["https://askspore.myceliumgastronomy.com/source/oauth/callback/sso-ssotest2/"]


@pytest.mark.parametrize("slug", ["ssotest2", "sso-", "sso-Bad", "sso-a/b", "sso-../x", "sso-a b"])
def test_the_source_slug_is_refused_unless_it_is_sso_and_a_tenant_slug(slug: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        setup().source_slug(slug)


def test_the_template_names_no_fixed_tenant() -> None:
    assert "ssotest" not in (DRILL / "realm.template.json").read_text("utf-8")
