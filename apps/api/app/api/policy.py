"""The login policy as the console and the tenant admin page show it (P1b-06, P1b-07)."""

from __future__ import annotations

from fastapi import Request

from app.api.schemas import LoginPolicyOut
from app.auth.sources import endpoints
from app.tenancy.login_policy import TenantLoginPolicy


def policy_out(request: Request, row: TenantLoginPolicy) -> LoginPolicyOut:
    """The policy, with the endpoints the client's IT registers for its source."""
    out = LoginPolicyOut.model_validate(row)
    authentik = request.app.state.settings.models.auth.authentik
    public_url = authentik.public_url if authentik is not None else None
    if row.sso_kind is not None and row.sso_source_slug and public_url:
        out.sso_endpoints = endpoints(public_url, row.sso_kind, row.sso_source_slug)
    return out
