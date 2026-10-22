"""Import every ORM module so ``Base.metadata`` describes the whole schema."""

from app.audit.models import AuditEvent
from app.auth.models import MfaChallenge, RevokedSession, SignInLink, SsoAttempt
from app.chat.models import Citation, Conversation, Feedback, Message
from app.content.jobs import Job
from app.content.models import ContentRole, Dataset, Source
from app.core.db import Base
from app.files.models import Download
from app.operator.models import Operator, OperatorNotice
from app.tenancy.login_policy import TenantLoginPolicy
from app.tenancy.models import Tenant, TenantEntitlements, TenantSettings, User
from app.tenancy.workspaces import Workspace, WorkspacePrompt
from app.usage.models import SpendNotice, UsageLedger

__all__ = [
    "AuditEvent",
    "Base",
    "Citation",
    "ContentRole",
    "Conversation",
    "Dataset",
    "Download",
    "Feedback",
    "Job",
    "Message",
    "MfaChallenge",
    "Operator",
    "OperatorNotice",
    "RevokedSession",
    "SignInLink",
    "Source",
    "SpendNotice",
    "SsoAttempt",
    "Tenant",
    "TenantEntitlements",
    "TenantLoginPolicy",
    "TenantSettings",
    "UsageLedger",
    "User",
    "Workspace",
    "WorkspacePrompt",
]
