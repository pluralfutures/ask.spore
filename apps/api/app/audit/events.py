"""The audit event catalogue (P2A-07): every event name the code writes, classified.

``EXPORTED_EVENTS`` is the explicit allow-list of the tenant admin's audit export
(``GET /api/v1/admin/audit-log``); everything else is ``OPERATOR_ONLY_EVENTS``. A name
is in exactly one of the two. ``app.audit.writer.record`` refuses a name in neither, and
``tests/test_audit_events.py`` scans the source tree for every name passed to
``record`` (directly or through a helper that forwards its ``event`` argument) and fails
on one that is not classified here, so a new event is never exported by default.

Exported: what a client's security contact asks for about their own organisation:
sign-in, the tenant admin's own actions, notice acceptance, downloads, workspace
instruction saves, operator actions on the tenant's users, and support access
(P2A-08). Not exported: query, feedback and conversation events (counted on the usage
section instead, P2A-05), the operator-only tenant-name flags (CLAUDE.md), model
fallbacks, operator changes to entitlements, login policy, SSO and workspaces, and the
platform's own content register, crawl, mail and purge events.
"""

from __future__ import annotations

from typing import Final

EXPORTED_EVENTS: Final[frozenset[str]] = frozenset(
    {
        # Sign-in (P1a-02, P1b-06 to P1b-08, P1c-02).
        "auth.link_refused",
        "auth.link_requested",
        "auth.login",
        "auth.login_failed",
        "auth.mfa_failed",
        "auth.role_from_sso",
        "auth.session_refreshed",
        "auth.signed_out",
        "auth.user_provisioned",
        # The use and privacy notice (P1b-10).
        "consent.accepted",
        # Downloads (P1a-14; owner decision 18, Oct 22, 2026).
        "download",
        "download.refused",
        # The tenant admin's own actions (P1a-13, P1c-07, P2A-07, P2A-08).
        "tenant_admin.audit_exported",
        "tenant_admin.invitation_resent",
        "tenant_admin.retention_changed",
        "tenant_admin.support_granted",
        "tenant_admin.support_revoked",
        "tenant_admin.user_changed",
        "tenant_admin.user_invited",
        "tenant_admin.user_removed",
        "tenant_admin.workspace_defaults_changed",
        # Operator actions on this tenant's users (P1a-03, P1c-07), and operator
        # grants, which are about the internal tenant's own users.
        "operator.admin_invited",
        "operator.granted",
        "operator.invitation_resent",
        "operator.revoked",
        "operator.user_removed",
        # Support access (P2A-08): every operator read through a grant, and a grant
        # closed by the daily purge job once expired.
        "operator.support_viewed",
        "support.grant_expired",
        # Workspace additional instructions (P1a-05).
        "workspace.prompt_saved",
    }
)

OPERATOR_ONLY_EVENTS: Final[frozenset[str]] = frozenset(
    {
        # Questions, feedback and conversations: counted on the usage section only.
        "chat.feedback",
        "chat.query",
        "conversation.deleted",
        # Model choice and failover (P1a-10).
        "model.fallback",
        # The tenant-name flag of tenant-authored instructions: operator only (CLAUDE.md).
        "workspace.prompt_tenant_name_match",
        # Operator configuration of a tenant (P1a-03, P1a-04, P1a-14, P1b-07).
        "operator.entitlements_changed",
        "operator.login_policy_changed",
        "operator.source_downloadable_changed",
        "operator.sso_source_changed",
        "operator.tenant_created",
        "operator.workspace_created",
        "operator.workspace_tags_changed",
        # Platform content: register, crawl, roles, datasets (internal tenant).
        "content.datasets_synced",
        "content_role.granted",
        "content_role.revoked",
        "ingest.source_retagged",
        "site.approved",
        "site.crawl_requested",
        "site.crawled",
        "site.proposed",
        "site.reinstated",  # P2A-12 (Group D), classified ahead of its build
        "site.rejected",
        "site.settings_changed",
        "site.special_category_allow_changed",
        "site.withdrawn",
        "source.approved",
        "source.failed",  # f"source.{result.status}" in app.content.ingest
        "source.ingested",  # likewise
        "source.licence_file_set",
        "source.paused",  # P2A-01 (Group A), classified ahead of its build
        "source.proposed",
        "source.rejected",
        "source.restored",
        "source.resumed",  # P2A-01 (Group A), classified ahead of its build
        "source.retag_approved",
        "source.retried",
        "source.takedown_recorded",
        "source.withdrawal_requested",
        "source.withdrawn",
        # Platform operations.
        "eval_identity.created",
        "mail.sent",
        "tenant.purged",
    }
)

AUDIT_EVENTS: Final[frozenset[str]] = EXPORTED_EVENTS | OPERATOR_ONLY_EVENTS

# Event names built at run time, with every value the code can produce.
DYNAMIC_EVENTS: Final[dict[str, frozenset[str]]] = {
    "source.{result.status}": frozenset({"source.ingested", "source.failed"}),
}
