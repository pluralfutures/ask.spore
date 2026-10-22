"""P1b-08: the Authentik blueprint reproduces the README's manual configuration.

CI applies ``infra/authentik/blueprints/ask-spore.yaml`` to an empty Authentik of the
pinned version and checks the result (job ``authentik-blueprint``,
``verify_blueprint.py``). This test runs everywhere, without Docker: it reads the file
with Authentik's tags, checks every reference resolves, and checks that what the API
relies on matches ``config/models.toml`` and the README, and that no secret is in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import DEFAULT_CONFIG_DIR, load_settings
from tests.test_config import ENV

REPO = Path(__file__).resolve().parents[3]
BLUEPRINT = REPO / "infra" / "authentik" / "blueprints" / "ask-spore.yaml"
VERIFY = REPO / "infra" / "authentik" / "blueprints" / "verify_blueprint.py"


@dataclass(frozen=True)
class KeyOf:
    id: str


@dataclass(frozen=True)
class Find:
    model: str
    query: tuple[Any, ...]


class Loader(yaml.SafeLoader):
    """Authentik's blueprint tags this file uses; any other tag fails to load."""


Loader.add_constructor("!KeyOf", lambda loader, node: KeyOf(loader.construct_scalar(node)))
Loader.add_constructor(
    "!Find",
    lambda loader, node: Find(
        loader.construct_sequence(node, deep=True)[0],
        tuple(loader.construct_sequence(node, deep=True)[1]),
    ),
)


@pytest.fixture(scope="module")
def blueprint() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load(BLUEPRINT.read_text(), Loader=Loader)  # noqa: S506
    return loaded


def entries(blueprint: dict[str, Any], model: str) -> list[dict[str, Any]]:
    return [e for e in blueprint["entries"] if e["model"] == model]


def one(blueprint: dict[str, Any], model: str, **identifiers: Any) -> dict[str, Any]:
    (found,) = [
        e
        for e in entries(blueprint, model)
        if all(e.get("identifiers", {}).get(k) == v for k, v in identifiers.items())
    ]
    return found


def by_id(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in blueprint["entries"] if "id" in e}


def stage_name(blueprint: dict[str, Any], ref: KeyOf) -> str:
    name: str = by_id(blueprint)[ref.id]["identifiers"]["name"]
    return name


def walk(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in walk(v)]
    if isinstance(value, list):
        return [x for v in value for x in walk(v)]
    return [value]


def test_every_reference_is_defined_before_use(blueprint: dict[str, Any]) -> None:
    assert blueprint["version"] == 1
    seen: set[str] = set()
    for entry in blueprint["entries"]:
        for ref in walk(entry):
            if isinstance(ref, KeyOf):
                assert ref.id in seen, f"!KeyOf {ref.id} used before it is defined"
        if "id" in entry:
            assert entry["id"] not in seen, f"duplicate id {entry['id']}"
            seen.add(entry["id"])
        assert entry["model"].startswith("authentik_"), entry["model"]
        if entry["model"] != "authentik_blueprints.metaapplyblueprint":
            assert entry.get("identifiers"), f"{entry['model']} needs identifiers"


def test_authentiks_own_objects_are_applied_first(blueprint: dict[str, Any]) -> None:
    applied = [e["attrs"]["identifiers"]["name"] for e in blueprint["entries"][:3]]
    assert all(
        e["model"] == "authentik_blueprints.metaapplyblueprint" for e in blueprint["entries"][:3]
    )
    assert applied == [
        "Default - Provider authorization flow (implicit consent)",
        "Default - Provider invalidation flow",
        "System - OAuth2 Provider - Scopes",
    ]


def settings_authentik() -> Any:
    authentik = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR).models.auth.authentik
    assert authentik is not None
    return authentik


def test_the_sign_in_link_flow_matches_the_readme_and_the_config(blueprint: dict[str, Any]) -> None:
    config = settings_authentik()
    flow = one(blueprint, "authentik_flows.flow", slug=config.sign_in_flow)
    assert flow["attrs"]["designation"] == "authentication"
    bindings = sorted(
        (b["identifiers"]["order"], stage_name(blueprint, b["identifiers"]["stage"]))
        for b in entries(blueprint, "authentik_flows.flowstagebinding")
        if b["identifiers"]["target"] == KeyOf(flow["id"])
    )
    assert bindings == [
        (10, "ask-spore-identification"),
        (20, "ask-spore-email-link"),
        (25, "ask-spore-admin-mfa"),  # P1b-08, between the email and the login
        (30, "ask-spore-login"),
    ]
    identification = one(
        blueprint,
        "authentik_stages_identification.identificationstage",
        name="ask-spore-identification",
    )["attrs"]
    assert identification["user_fields"] == ["email"] and identification["sources"] == []
    assert identification["pretend_user_exists"] is True  # no enumeration
    email = one(blueprint, "authentik_stages_email.emailstage", name="ask-spore-email-link")[
        "attrs"
    ]
    assert email["token_expiry"] == "minutes=15"
    assert email["template"] == "ask-spore-sign-in.html"
    assert (REPO / "infra" / "authentik" / "templates" / email["template"]).exists()
    assert email["activate_user_on_success"] is False and email["use_global_settings"] is True
    login = one(blueprint, "authentik_stages_user_login.userloginstage", name="ask-spore-login")
    assert login["attrs"]["session_duration"] == "hours=8"


def test_the_second_factor_is_bound_to_the_admin_group(blueprint: dict[str, Any]) -> None:
    config = settings_authentik()
    stage = one(
        blueprint,
        "authentik_stages_authenticator_validate.authenticatorvalidatestage",
        name="ask-spore-admin-mfa",
    )["attrs"]
    assert stage["device_classes"] == ["totp"]  # the API relays TOTP only
    assert stage["not_configured_action"] == "configure"
    assert stage["last_auth_threshold"] == "seconds=0"
    (setup,) = stage["configuration_stages"]
    assert stage_name(blueprint, setup) == "ask-spore-admin-totp-setup"
    binding = by_id(blueprint)["binding-admin-mfa"]
    assert binding["attrs"] == {"evaluate_on_plan": False, "re_evaluate_policies": True}
    (policy,) = [
        p
        for p in entries(blueprint, "authentik_policies.policybinding")
        if p["identifiers"]["target"] == KeyOf("binding-admin-mfa")
    ]
    group = by_id(blueprint)[policy["identifiers"]["group"].id]
    assert group["identifiers"]["name"] == config.admin_mfa_group


def test_source_flows_match_the_config(blueprint: dict[str, Any]) -> None:
    config = settings_authentik()
    expected = {
        config.source_authentication_flow: ("authentication", "never_create"),
        config.source_enrollment_flow: ("enrollment", "always_create"),
    }
    for slug, (designation, creation) in expected.items():
        flow = one(blueprint, "authentik_flows.flow", slug=slug)
        assert flow["attrs"]["designation"] == designation
        stages = [
            by_id(blueprint)[b["identifiers"]["stage"].id]
            for b in entries(blueprint, "authentik_flows.flowstagebinding")
            if b["identifiers"]["target"] == KeyOf(flow["id"])
        ]
        writes = [s for s in stages if s["model"] == "authentik_stages_user_write.userwritestage"]
        assert [w["attrs"]["user_creation_mode"] for w in writes] == [creation]
        guards = [
            p
            for p in entries(blueprint, "authentik_policies.policybinding")
            if p["identifiers"]["target"] == KeyOf(flow["id"])
        ]
        assert [g["identifiers"]["policy"] for g in guards] == [KeyOf("policy-if-sso")]
    create = one(
        blueprint, "authentik_stages_user_write.userwritestage", name="ask-spore-source-create"
    )
    assert create["attrs"]["user_path_template"] == "ask-spore/sso"
    pre = one(blueprint, "authentik_flows.flow", slug=config.source_pre_authentication_flow)
    assert pre["attrs"]["designation"] == "stage_configuration"


def test_provider_and_application_match_the_config(blueprint: dict[str, Any]) -> None:
    config = settings_authentik()
    provider = one(blueprint, "authentik_providers_oauth2.oauth2provider", name="ask-spore")[
        "attrs"
    ]
    assert provider["client_id"] == config.client_id
    assert provider["client_type"] == "confidential"
    assert provider["redirect_uris"] == [{"matching_mode": "strict", "url": config.redirect_uri}]
    assert provider["grant_types"] == ["authorization_code", "refresh_token"]  # F1, P1b-08
    assert provider["access_token_validity"] == "hours=8"
    refresh = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR).models.auth
    assert (
        provider["refresh_token_validity"] == f"hours={refresh.refresh_token_ttl_seconds // 3600}"
    )
    # A certificate signs the tokens (RS256): the API refuses HS256.
    assert provider["signing_key"] == Find(
        "authentik_crypto.certificatekeypair", ("name", "authentik Self-signed Certificate")
    )
    assert provider["sub_mode"] == "hashed_user_id"
    scopes = {
        ref.query[1].rsplit("scope-", 1)[1] if isinstance(ref, Find) else ref.id
        for ref in provider["property_mappings"]
    }
    assert scopes == {"openid", "email", "profile", "offline_access", "scope-ask-spore"}
    mapping = by_id(blueprint)["scope-ask-spore"]["attrs"]
    assert mapping["scope_name"] == "ask_spore"
    assert (
        '"ask_spore_tenant": request.user.attributes.get("ask_spore_tenant")'
        in mapping["expression"]
    )
    assert '"ask_spore_sso": request.user.attributes.get("ask_spore_sso")' in mapping["expression"]
    application = one(blueprint, "authentik_core.application", slug=config.client_id)
    assert application["attrs"]["provider"] == KeyOf("provider")


def test_the_provisioner_can_do_what_the_api_asks_and_no_more(blueprint: dict[str, Any]) -> None:
    role = one(blueprint, "authentik_rbac.role", name="ask-spore-provisioner")["attrs"]
    permissions = set(role["permissions"])
    assert {
        "authentik_core.view_user",
        "authentik_core.add_user",
        "authentik_core.change_user",
        "authentik_core.add_user_to_group",
        "authentik_core.remove_user_from_group",
        "authentik_sources_oauth.add_oauthsource",
        "authentik_sources_saml.add_samlsource",
        "authentik_crypto.add_certificatekeypair",
        "authentik_flows.view_flow",
    } <= permissions
    for refused in ("delete_user", "change_flow", "view_token", "view_certificatekeypair_key"):
        assert not any(p.endswith(refused) for p in permissions), refused
    user = one(blueprint, "authentik_core.user", username="ask-spore-provisioner")["attrs"]
    assert user["type"] == "service_account" and user["roles"] == [KeyOf("role-provisioner")]
    token = one(blueprint, "authentik_core.token", identifier="ask-spore-provisioner-api")
    assert token["state"] == "created"  # re-applying never rotates it
    assert token["attrs"]["intent"] == "api" and "key" not in token["attrs"]


def test_no_secret_is_in_the_blueprint(blueprint: dict[str, Any]) -> None:
    for entry in blueprint["entries"]:
        attrs = entry.get("attrs", {})
        for field in ("client_secret", "password", "password_hash", "key", "key_data"):
            assert field not in attrs, f"{entry['model']} sets {field}"
    text = BLUEPRINT.read_text()
    assert not re.search(r"(?i)secret\s*:", text)


def test_ci_applies_it_to_an_empty_authentik() -> None:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert "authentik-blueprint:" in workflow
    assert "apply_blueprint custom/ask-spore.yaml" in workflow
    assert "apply_blueprint --dry-run custom/ask-spore.yaml" in workflow
    assert "blueprints/verify_blueprint.py" in workflow
    compose = (REPO / "infra" / "authentik" / "docker-compose.yml").read_text()
    assert compose.count("./blueprints:/blueprints/custom:ro") == 2  # server and worker
    assert "blueprints/wait_for_defaults.py" in workflow
    # The scripts run in Authentik's shell from stdin: they must at least be valid Python.
    for script in (VERIFY, VERIFY.with_name("wait_for_defaults.py")):
        compile(script.read_text(), str(script), "exec")
