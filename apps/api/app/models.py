"""Import every ORM module so ``Base.metadata`` describes the whole schema."""

from app.audit.models import AuditEvent
from app.auth.models import RevokedSession, SignInLink
from app.chat.models import Citation, Conversation, Feedback, Message
from app.content.models import Dataset, Source
from app.core.db import Base
from app.operator.models import Operator, OperatorNotice
from app.tenancy.models import Tenant, TenantEntitlements, User
from app.tenancy.workspaces import Workspace, WorkspacePrompt
from app.usage.models import SpendNotice, UsageLedger

__all__ = [
    "AuditEvent",
    "Base",
    "Citation",
    "Conversation",
    "Dataset",
    "Feedback",
    "Message",
    "Operator",
    "OperatorNotice",
    "RevokedSession",
    "SignInLink",
    "Source",
    "SpendNotice",
    "Tenant",
    "TenantEntitlements",
    "UsageLedger",
    "User",
    "Workspace",
    "WorkspacePrompt",
]
