# Checks an Authentik that ask-spore.yaml was applied to (P1b-08). Run inside the worker:
#   docker compose -f infra/authentik/docker-compose.yml --profile auth \
#     exec -T authentik-worker ak shell < infra/authentik/blueprints/verify_blueprint.py
# Exits non-zero, naming what is missing, when the result is not what the API relies on
# (infra/authentik/README.md, "Configuration the API relies on"). Not a .yaml file, so
# Authentik's blueprint discovery ignores it. Prints names only, never a secret.
from authentik.core.models import Application, Group, Token, User
from authentik.flows.models import Flow, FlowStageBinding
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import OAuth2Provider, ScopeMapping

problems = []


def need(condition, what):
    if not condition:
        problems.append(what)


flow = Flow.objects.filter(slug="ask-spore-sign-in-link", designation="authentication").first()
need(flow is not None, "flow ask-spore-sign-in-link")
if flow is not None:
    order = [
        (b.order, b.stage.name)
        for b in FlowStageBinding.objects.filter(target=flow).order_by("order")
    ]
    expected = [
        (10, "ask-spore-identification"),
        (20, "ask-spore-email-link"),
        (25, "ask-spore-admin-mfa"),
        (30, "ask-spore-login"),
    ]
    need(order == expected, f"sign-in-link stages {order}")
    mfa = FlowStageBinding.objects.filter(target=flow, order=25).first()
    need(
        mfa is not None
        and PolicyBinding.objects.filter(target=mfa, group__name="ask-spore-tenant-admins").exists(),
        "admin MFA stage bound to group ask-spore-tenant-admins",
    )
for slug, designation in (
    ("ask-spore-source-authentication", "authentication"),
    ("ask-spore-source-enrollment", "enrollment"),
    ("ask-spore-source-pre-authentication", "stage_configuration"),
):
    need(Flow.objects.filter(slug=slug, designation=designation).exists(), f"flow {slug}")

provider = OAuth2Provider.objects.filter(name="ask-spore").first()
need(provider is not None, "provider ask-spore")
if provider is not None:
    need(provider.client_id == "ask-spore", "provider client ID")
    need(provider.client_type == "confidential", "confidential client")
    need(
        set(provider.grant_types) == {"authorization_code", "refresh_token"},
        f"grant types {provider.grant_types}",
    )
    need(provider.signing_key is not None, "provider signing key (RS256, not HS256)")
    need(provider.access_token_validity == "hours=8", "access token validity")
    need(provider.refresh_token_validity == "hours=24", "refresh token validity")
    scopes = set(
        ScopeMapping.objects.filter(
            pk__in=provider.property_mappings.values_list("pk", flat=True)
        ).values_list("scope_name", flat=True)
    )
    need(
        {"openid", "email", "profile", "offline_access", "ask_spore"} <= scopes,
        f"scopes {sorted(scopes)}",
    )
    need(
        Application.objects.filter(slug="ask-spore", provider=provider).exists(),
        "application ask-spore",
    )
mapping = ScopeMapping.objects.filter(scope_name="ask_spore").first()
need(
    mapping is not None
    and "ask_spore_tenant" in mapping.expression
    and "ask_spore_sso" in mapping.expression,
    "scope mapping ask_spore",
)
need(Group.objects.filter(name="ask-spore-tenant-admins").exists(), "group ask-spore-tenant-admins")
provisioner = User.objects.filter(username="ask-spore-provisioner").first()
need(provisioner is not None, "user ask-spore-provisioner")
if provisioner is not None:
    need(provisioner.type == "service_account", "provisioner is a service account")
    need(
        Token.objects.filter(
            identifier="ask-spore-provisioner-api", intent="api", user=provisioner
        ).exists(),
        "provisioner API token",
    )

if problems:
    print("ask.spore blueprint check FAILED:", "; ".join(problems))
    raise SystemExit(1)
print("ask.spore blueprint check ok")
